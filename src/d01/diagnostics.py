from __future__ import annotations

import importlib.metadata
import platform
import shutil
import subprocess
import sys
import time
import warnings

from d01.common import PROJECT_ROOT, utc_now


def environment_report(gpu_test: bool = False) -> dict:
    packages = {}
    for name in ("torch", "numpy", "pandas", "pydantic", "jsonschema", "pytest",
                 "transformers", "accelerate", "bitsandbytes"):
        try:
            packages[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            packages[name] = None
    disk = shutil.disk_usage(PROJECT_ROOT)
    report = {"created_at_utc": utc_now(), "kind": "environment_diagnostic",
              "python": {"version": platform.python_version(), "executable": sys.executable,
                         "prefix": sys.prefix, "base_prefix": sys.base_prefix,
                         "isolated": sys.prefix != sys.base_prefix},
              "platform": platform.platform(), "packages": packages,
              "disk_bytes": {"free": disk.free, "total": disk.total},
              "gpu_test_requested": gpu_test, "competition_model_tested": False}
    try:
        result = subprocess.run(["nvidia-smi", "--query-gpu=name,memory.total,driver_version,compute_cap",
                                 "--format=csv,noheader"], capture_output=True, text=True, timeout=15)
        report["nvidia_smi"] = {"exit_code": result.returncode, "output": result.stdout.strip(),
                                "error": result.stderr.strip()}
    except (OSError, subprocess.TimeoutExpired) as exc:
        report["nvidia_smi"] = {"error": type(exc).__name__}
    if not gpu_test:
        report["status"] = "INVENTORY_ONLY"
        return report
    try:
        import torch
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            if not torch.cuda.is_available():
                raise RuntimeError("CUDA unavailable")
            device = torch.device("cuda:0")
            capability = torch.cuda.get_device_capability(device)
            arches = torch.cuda.get_arch_list()
            if f"sm_{capability[0]}{capability[1]}" not in arches:
                report["status"] = "ARCH_REVIEW_REQUIRED"
                report["cuda"] = {"torch_runtime": torch.version.cuda, "capability": list(capability),
                                  "compiled_arches": arches, "native_arch_listed": False,
                                  "warnings": [str(w.message) for w in caught]}
                report["limitations"] = ["Native device architecture not listed; GPU kernels skipped",
                                         "PTX fallback and complete model compatibility are not established"]
                return report
            torch.manual_seed(20261028)
            torch.cuda.manual_seed_all(20261028)
            torch.cuda.reset_peak_memory_stats(device)
            # Nontrivial matrix + attention kernels; this is not a 27B capacity benchmark.
            x = torch.randn((1024, 1024), device=device, dtype=torch.float32) * 0.01
            y = torch.randn_like(x) * 0.01
            torch.cuda.synchronize()
            start = time.perf_counter()
            gpu_product = x @ y
            torch.cuda.synchronize()
            elapsed = time.perf_counter() - start
            reference = x.cpu().double() @ y.cpu().double()
            error = float((gpu_product.cpu().double() - reference).abs().max())
            torch.testing.assert_close(gpu_product.cpu().double(), reference, rtol=1e-3, atol=1e-5)
            q = torch.randn((1, 4, 128, 64), device=device, dtype=torch.bfloat16)
            attention = torch.nn.functional.scaled_dot_product_attention(q, q, q, is_causal=True)
            assert torch.isfinite(attention).all().item(), "Nonfinite attention output"
            layer = torch.nn.Linear(256, 256, device=device, dtype=torch.bfloat16)
            optimizer = torch.optim.AdamW(layer.parameters(), lr=1e-4)
            optimizer.zero_grad(set_to_none=True)
            loss = layer(torch.randn((4, 256), device=device, dtype=torch.bfloat16)).float().square().mean()
            loss.backward()
            optimizer.step()
            assert torch.isfinite(loss).item(), "Nonfinite training probe loss"
            torch.cuda.synchronize()
            report["cuda"] = {"torch_runtime": torch.version.cuda, "capability": list(capability),
                              "compiled_arches": arches,
                              "native_arch_listed": f"sm_{capability[0]}{capability[1]}" in arches,
                              "device_name": torch.cuda.get_device_name(device),
                              "total_memory_bytes": torch.cuda.get_device_properties(device).total_memory,
                              "matmul_shape": [1024, 1024], "matmul_seconds": elapsed,
                              "matmul_max_absolute_error": error,
                              "bf16_causal_attention": "PASS", "bf16_backward_adamw": "PASS",
                              "peak_allocated_bytes": torch.cuda.max_memory_allocated(device),
                              "warnings": [str(w.message) for w in caught]}
            report["status"] = "PASS" if report["cuda"]["native_arch_listed"] else "ARCH_REVIEW_REQUIRED"
    except Exception as exc:
        report["status"] = "FAIL"
        report["gpu_error"] = {"type": type(exc).__name__, "message": str(exc)}
    report["limitations"] = ["Small kernel probes only; no 27B model, quantization kernels or long context tested",
                             "Timings include initial kernel overhead; not a throughput benchmark"]
    return report
