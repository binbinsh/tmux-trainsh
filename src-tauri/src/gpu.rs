//! GPU information types and capability database.
//!
//! Contains GPU runtime info structures and a static database of
//! NVIDIA GPU capabilities (CUDA cores, Tensor cores, TFLOPS, etc.)

use serde::{Deserialize, Serialize};

// ============================================================
// GPU Types
// ============================================================

/// Runtime GPU information collected from nvidia-smi
#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct GpuInfo {
    pub index: i32,
    pub name: String,
    pub memory_total_mb: i64,
    pub memory_used_mb: Option<i64>,
    pub utilization: Option<i32>,
    pub temperature: Option<i32>,
    // Extended runtime info
    pub driver_version: Option<String>,
    pub power_draw_w: Option<f64>,
    pub power_limit_w: Option<f64>,
    pub clock_graphics_mhz: Option<i32>,
    pub clock_memory_mhz: Option<i32>,
    pub fan_speed: Option<i32>,
    pub compute_mode: Option<String>,
    pub pcie_gen: Option<i32>,
    pub pcie_width: Option<i32>,
    // Static capability info (looked up by GPU model)
    pub capability: Option<GpuCapability>,
}

/// Static GPU capability information (architecture, cores, TFLOPS, etc.)
#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct GpuCapability {
    pub architecture: String,
    pub compute_capability: String,
    pub cuda_cores: i32,
    pub tensor_cores: Option<i32>,
    pub tensor_core_gen: Option<i32>,
    pub rt_cores: Option<i32>,
    pub rt_core_gen: Option<i32>,
    pub memory_bandwidth_gbps: Option<f64>,
    // Theoretical peak performance (TFLOPS, with sparsity where applicable)
    pub fp32_tflops: Option<f64>,
    pub fp16_tflops: Option<f64>,
    pub bf16_tflops: Option<f64>,
    pub fp8_tflops: Option<f64>,
    pub fp4_tflops: Option<f64>, // Blackwell 5th gen Tensor Core
    pub int8_tops: Option<f64>,
    pub tf32_tflops: Option<f64>,
}

// ============================================================
// GPU Capability Database
// ============================================================

/// Lookup GPU capability by model name.
/// Returns static capability info based on known GPU models.
pub fn lookup_gpu_capability(name: &str) -> Option<GpuCapability> {
    let name_upper = name.to_uppercase();

    // ============================================================
    // NVIDIA Blackwell Architecture (RTX 50 Series)
    // Data from NVIDIA RTX Blackwell GPU Architecture whitepaper
    // ============================================================

    // GeForce RTX 5090 (GB202)
    if name_upper.contains("5090") && !name_upper.contains("5090D") {
        return Some(GpuCapability {
            architecture: "Blackwell".to_string(),
            compute_capability: "10.0".to_string(),
            cuda_cores: 21760,
            tensor_cores: Some(680),
            tensor_core_gen: Some(5),
            rt_cores: Some(170),
            rt_core_gen: Some(4),
            memory_bandwidth_gbps: Some(1792.0), // 32GB GDDR7
            fp32_tflops: Some(104.8),
            fp16_tflops: Some(419.2), // With sparsity
            bf16_tflops: Some(419.2),
            fp8_tflops: Some(838.4),  // With sparsity
            fp4_tflops: Some(1676.8), // With sparsity - new in Blackwell
            int8_tops: Some(1676.8),  // With sparsity
            tf32_tflops: Some(209.6), // With sparsity
        });
    }

    // GeForce RTX 5090D (China variant, reduced specs)
    if name_upper.contains("5090D") {
        return Some(GpuCapability {
            architecture: "Blackwell".to_string(),
            compute_capability: "10.0".to_string(),
            cuda_cores: 19456, // Reduced for China
            tensor_cores: Some(608),
            tensor_core_gen: Some(5),
            rt_cores: Some(152),
            rt_core_gen: Some(4),
            memory_bandwidth_gbps: Some(1792.0),
            fp32_tflops: Some(93.6),
            fp16_tflops: Some(374.4),
            bf16_tflops: Some(374.4),
            fp8_tflops: Some(748.8),
            fp4_tflops: Some(1497.6),
            int8_tops: Some(1497.6),
            tf32_tflops: Some(187.2),
        });
    }

    // GeForce RTX 5080 (GB203)
    if name_upper.contains("5080") {
        return Some(GpuCapability {
            architecture: "Blackwell".to_string(),
            compute_capability: "10.0".to_string(),
            cuda_cores: 10752,
            tensor_cores: Some(336),
            tensor_core_gen: Some(5),
            rt_cores: Some(84),
            rt_core_gen: Some(4),
            memory_bandwidth_gbps: Some(960.0), // 16GB GDDR7
            fp32_tflops: Some(56.3),
            fp16_tflops: Some(225.2),
            bf16_tflops: Some(225.2),
            fp8_tflops: Some(450.4),
            fp4_tflops: Some(900.8),
            int8_tops: Some(900.8),
            tf32_tflops: Some(112.6),
        });
    }

    // GeForce RTX 5070 Ti (GB203)
    if name_upper.contains("5070") && name_upper.contains("TI") {
        return Some(GpuCapability {
            architecture: "Blackwell".to_string(),
            compute_capability: "10.0".to_string(),
            cuda_cores: 8960,
            tensor_cores: Some(280),
            tensor_core_gen: Some(5),
            rt_cores: Some(70),
            rt_core_gen: Some(4),
            memory_bandwidth_gbps: Some(896.0), // 16GB GDDR7
            fp32_tflops: Some(43.9),
            fp16_tflops: Some(175.7),
            bf16_tflops: Some(175.7),
            fp8_tflops: Some(351.5),
            fp4_tflops: Some(703.0),
            int8_tops: Some(703.0),
            tf32_tflops: Some(87.9),
        });
    }

    // GeForce RTX 5070 (GB205)
    if name_upper.contains("5070") && !name_upper.contains("TI") {
        return Some(GpuCapability {
            architecture: "Blackwell".to_string(),
            compute_capability: "10.0".to_string(),
            cuda_cores: 6144,
            tensor_cores: Some(192),
            tensor_core_gen: Some(5),
            rt_cores: Some(48),
            rt_core_gen: Some(4),
            memory_bandwidth_gbps: Some(672.0), // 12GB GDDR7
            fp32_tflops: Some(30.9),
            fp16_tflops: Some(123.5),
            bf16_tflops: Some(123.5),
            fp8_tflops: Some(246.9),
            fp4_tflops: Some(493.9),
            int8_tops: Some(493.9),
            tf32_tflops: Some(61.7),
        });
    }

    // ============================================================
    // NVIDIA Hopper Architecture (Datacenter)
    // ============================================================

    // H100 series
    if name_upper.contains("H100") {
        return Some(GpuCapability {
            architecture: "Hopper".to_string(),
            compute_capability: "9.0".to_string(),
            cuda_cores: 16896,
            tensor_cores: Some(528),
            tensor_core_gen: Some(4),
            rt_cores: None,
            rt_core_gen: None,
            memory_bandwidth_gbps: Some(3350.0),
            fp32_tflops: Some(67.0),
            fp16_tflops: Some(1979.0),
            bf16_tflops: Some(1979.0),
            fp8_tflops: Some(3958.0),
            fp4_tflops: None,
            int8_tops: Some(3958.0),
            tf32_tflops: Some(989.0),
        });
    }

    // H200
    if name_upper.contains("H200") {
        return Some(GpuCapability {
            architecture: "Hopper".to_string(),
            compute_capability: "9.0".to_string(),
            cuda_cores: 16896,
            tensor_cores: Some(528),
            tensor_core_gen: Some(4),
            rt_cores: None,
            rt_core_gen: None,
            memory_bandwidth_gbps: Some(4800.0), // 141GB HBM3e
            fp32_tflops: Some(67.0),
            fp16_tflops: Some(1979.0),
            bf16_tflops: Some(1979.0),
            fp8_tflops: Some(3958.0),
            fp4_tflops: None,
            int8_tops: Some(3958.0),
            tf32_tflops: Some(989.0),
        });
    }

    // ============================================================
    // NVIDIA Ampere Architecture (Datacenter)
    // ============================================================

    // A100 series
    if name_upper.contains("A100") {
        let is_80gb = name_upper.contains("80G") || name_upper.contains("SXM");
        return Some(GpuCapability {
            architecture: "Ampere".to_string(),
            compute_capability: "8.0".to_string(),
            cuda_cores: 6912,
            tensor_cores: Some(432),
            tensor_core_gen: Some(3),
            rt_cores: None,
            rt_core_gen: None,
            memory_bandwidth_gbps: Some(if is_80gb { 2039.0 } else { 1555.0 }),
            fp32_tflops: Some(19.5),
            fp16_tflops: Some(312.0),
            bf16_tflops: Some(312.0),
            fp8_tflops: None,
            fp4_tflops: None,
            int8_tops: Some(624.0),
            tf32_tflops: Some(156.0),
        });
    }

    // ============================================================
    // NVIDIA Ada Lovelace Architecture (RTX 40 Series)
    // ============================================================

    // L40 / L40S
    if name_upper.contains("L40") {
        return Some(GpuCapability {
            architecture: "Ada Lovelace".to_string(),
            compute_capability: "8.9".to_string(),
            cuda_cores: 18176,
            tensor_cores: Some(568),
            tensor_core_gen: Some(4),
            rt_cores: Some(142),
            rt_core_gen: Some(3),
            memory_bandwidth_gbps: Some(864.0),
            fp32_tflops: Some(90.5),
            fp16_tflops: Some(362.0),
            bf16_tflops: Some(362.0),
            fp8_tflops: Some(724.0),
            fp4_tflops: None,
            int8_tops: Some(724.0),
            tf32_tflops: Some(181.0),
        });
    }

    // RTX 4090
    if name_upper.contains("4090") {
        return Some(GpuCapability {
            architecture: "Ada Lovelace".to_string(),
            compute_capability: "8.9".to_string(),
            cuda_cores: 16384,
            tensor_cores: Some(512),
            tensor_core_gen: Some(4),
            rt_cores: Some(128),
            rt_core_gen: Some(3),
            memory_bandwidth_gbps: Some(1008.0),
            fp32_tflops: Some(82.6),
            fp16_tflops: Some(330.3),
            bf16_tflops: Some(330.3),
            fp8_tflops: Some(660.6),
            fp4_tflops: None,
            int8_tops: Some(660.6),
            tf32_tflops: Some(165.2),
        });
    }

    // RTX 4080 Super
    if name_upper.contains("4080") && name_upper.contains("SUPER") {
        return Some(GpuCapability {
            architecture: "Ada Lovelace".to_string(),
            compute_capability: "8.9".to_string(),
            cuda_cores: 10240,
            tensor_cores: Some(320),
            tensor_core_gen: Some(4),
            rt_cores: Some(80),
            rt_core_gen: Some(3),
            memory_bandwidth_gbps: Some(736.0),
            fp32_tflops: Some(52.2),
            fp16_tflops: Some(208.9),
            bf16_tflops: Some(208.9),
            fp8_tflops: Some(417.8),
            fp4_tflops: None,
            int8_tops: Some(417.8),
            tf32_tflops: Some(104.4),
        });
    }

    // RTX 4080
    if name_upper.contains("4080") {
        return Some(GpuCapability {
            architecture: "Ada Lovelace".to_string(),
            compute_capability: "8.9".to_string(),
            cuda_cores: 9728,
            tensor_cores: Some(304),
            tensor_core_gen: Some(4),
            rt_cores: Some(76),
            rt_core_gen: Some(3),
            memory_bandwidth_gbps: Some(716.8),
            fp32_tflops: Some(48.7),
            fp16_tflops: Some(194.9),
            bf16_tflops: Some(194.9),
            fp8_tflops: Some(389.8),
            fp4_tflops: None,
            int8_tops: Some(389.8),
            tf32_tflops: Some(97.5),
        });
    }

    // RTX 4070 Ti Super
    if name_upper.contains("4070") && name_upper.contains("TI") && name_upper.contains("SUPER") {
        return Some(GpuCapability {
            architecture: "Ada Lovelace".to_string(),
            compute_capability: "8.9".to_string(),
            cuda_cores: 8448,
            tensor_cores: Some(264),
            tensor_core_gen: Some(4),
            rt_cores: Some(66),
            rt_core_gen: Some(3),
            memory_bandwidth_gbps: Some(672.0),
            fp32_tflops: Some(44.1),
            fp16_tflops: Some(176.4),
            bf16_tflops: Some(176.4),
            fp8_tflops: Some(352.8),
            fp4_tflops: None,
            int8_tops: Some(352.8),
            tf32_tflops: Some(88.2),
        });
    }

    // RTX 4070 Ti
    if name_upper.contains("4070") && name_upper.contains("TI") {
        return Some(GpuCapability {
            architecture: "Ada Lovelace".to_string(),
            compute_capability: "8.9".to_string(),
            cuda_cores: 7680,
            tensor_cores: Some(240),
            tensor_core_gen: Some(4),
            rt_cores: Some(60),
            rt_core_gen: Some(3),
            memory_bandwidth_gbps: Some(504.0),
            fp32_tflops: Some(40.1),
            fp16_tflops: Some(160.4),
            bf16_tflops: Some(160.4),
            fp8_tflops: Some(320.8),
            fp4_tflops: None,
            int8_tops: Some(320.8),
            tf32_tflops: Some(80.2),
        });
    }

    // ============================================================
    // NVIDIA Ampere Architecture (RTX 30 Series)
    // ============================================================

    // RTX 3090 Ti
    if name_upper.contains("3090") && name_upper.contains("TI") {
        return Some(GpuCapability {
            architecture: "Ampere".to_string(),
            compute_capability: "8.6".to_string(),
            cuda_cores: 10752,
            tensor_cores: Some(336),
            tensor_core_gen: Some(3),
            rt_cores: Some(84),
            rt_core_gen: Some(2),
            memory_bandwidth_gbps: Some(1008.0),
            fp32_tflops: Some(40.0),
            fp16_tflops: Some(160.0),
            bf16_tflops: Some(160.0),
            fp8_tflops: None,
            fp4_tflops: None,
            int8_tops: Some(320.0),
            tf32_tflops: Some(80.0),
        });
    }

    // RTX 3090
    if name_upper.contains("3090") {
        return Some(GpuCapability {
            architecture: "Ampere".to_string(),
            compute_capability: "8.6".to_string(),
            cuda_cores: 10496,
            tensor_cores: Some(328),
            tensor_core_gen: Some(3),
            rt_cores: Some(82),
            rt_core_gen: Some(2),
            memory_bandwidth_gbps: Some(936.2),
            fp32_tflops: Some(35.6),
            fp16_tflops: Some(142.0),
            bf16_tflops: Some(142.0),
            fp8_tflops: None,
            fp4_tflops: None,
            int8_tops: Some(284.0),
            tf32_tflops: Some(71.0),
        });
    }

    // RTX 3080 Ti
    if name_upper.contains("3080") && name_upper.contains("TI") {
        return Some(GpuCapability {
            architecture: "Ampere".to_string(),
            compute_capability: "8.6".to_string(),
            cuda_cores: 10240,
            tensor_cores: Some(320),
            tensor_core_gen: Some(3),
            rt_cores: Some(80),
            rt_core_gen: Some(2),
            memory_bandwidth_gbps: Some(912.0),
            fp32_tflops: Some(34.1),
            fp16_tflops: Some(136.4),
            bf16_tflops: Some(136.4),
            fp8_tflops: None,
            fp4_tflops: None,
            int8_tops: Some(272.8),
            tf32_tflops: Some(68.2),
        });
    }

    // RTX 3080
    if name_upper.contains("3080") {
        return Some(GpuCapability {
            architecture: "Ampere".to_string(),
            compute_capability: "8.6".to_string(),
            cuda_cores: 8704,
            tensor_cores: Some(272),
            tensor_core_gen: Some(3),
            rt_cores: Some(68),
            rt_core_gen: Some(2),
            memory_bandwidth_gbps: Some(760.3),
            fp32_tflops: Some(29.8),
            fp16_tflops: Some(119.0),
            bf16_tflops: Some(119.0),
            fp8_tflops: None,
            fp4_tflops: None,
            int8_tops: Some(238.0),
            tf32_tflops: Some(59.5),
        });
    }

    // RTX A6000
    if name_upper.contains("A6000") {
        return Some(GpuCapability {
            architecture: "Ampere".to_string(),
            compute_capability: "8.6".to_string(),
            cuda_cores: 10752,
            tensor_cores: Some(336),
            tensor_core_gen: Some(3),
            rt_cores: Some(84),
            rt_core_gen: Some(2),
            memory_bandwidth_gbps: Some(768.0),
            fp32_tflops: Some(38.7),
            fp16_tflops: Some(155.0),
            bf16_tflops: Some(155.0),
            fp8_tflops: None,
            fp4_tflops: None,
            int8_tops: Some(310.0),
            tf32_tflops: Some(77.4),
        });
    }

    // ============================================================
    // NVIDIA Volta / Turing Architecture (Datacenter & Older)
    // ============================================================

    // Tesla V100
    if name_upper.contains("V100") {
        return Some(GpuCapability {
            architecture: "Volta".to_string(),
            compute_capability: "7.0".to_string(),
            cuda_cores: 5120,
            tensor_cores: Some(640),
            tensor_core_gen: Some(1),
            rt_cores: None,
            rt_core_gen: None,
            memory_bandwidth_gbps: Some(900.0),
            fp32_tflops: Some(15.7),
            fp16_tflops: Some(125.0),
            bf16_tflops: None,
            fp8_tflops: None,
            fp4_tflops: None,
            int8_tops: None,
            tf32_tflops: None,
        });
    }

    // Tesla T4
    if name_upper.contains("T4") && !name_upper.contains("RTX") {
        return Some(GpuCapability {
            architecture: "Turing".to_string(),
            compute_capability: "7.5".to_string(),
            cuda_cores: 2560,
            tensor_cores: Some(320),
            tensor_core_gen: Some(2),
            rt_cores: None, // T4 has RT cores but primarily for inference
            rt_core_gen: None,
            memory_bandwidth_gbps: Some(320.0),
            fp32_tflops: Some(8.1),
            fp16_tflops: Some(65.0),
            bf16_tflops: None,
            fp8_tflops: None,
            fp4_tflops: None,
            int8_tops: Some(130.0),
            tf32_tflops: None,
        });
    }

    // A10
    if name_upper.contains("A10") && !name_upper.contains("A100") {
        return Some(GpuCapability {
            architecture: "Ampere".to_string(),
            compute_capability: "8.6".to_string(),
            cuda_cores: 9216,
            tensor_cores: Some(288),
            tensor_core_gen: Some(3),
            rt_cores: Some(72),
            rt_core_gen: Some(2),
            memory_bandwidth_gbps: Some(600.0),
            fp32_tflops: Some(31.2),
            fp16_tflops: Some(125.0),
            bf16_tflops: Some(125.0),
            fp8_tflops: None,
            fp4_tflops: None,
            int8_tops: Some(250.0),
            tf32_tflops: Some(62.5),
        });
    }

    None
}
