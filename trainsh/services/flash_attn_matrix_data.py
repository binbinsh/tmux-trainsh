"""Data-only FlashAttention compatibility matrix rows."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class FlashAttnCompatRule:
    """One explicit compatibility matrix row for FlashAttention selection."""

    rule_id: str
    backend: str
    families: tuple[str, ...]
    package_name: str
    strategy: str
    target: str
    default_install_spec: str
    unsupported_reason: str = ""
    install_env: dict[str, str] = field(default_factory=dict)


FLASH_ATTN_COMPAT_RULES: tuple[FlashAttnCompatRule, ...] = (
    FlashAttnCompatRule(
        rule_id="cuda_turing_unsupported",
        backend="cuda",
        families=("turing",),
        package_name="flash-attn",
        strategy="unsupported",
        target="unsupported",
        default_install_spec="flash-attn",
        unsupported_reason="Turing GPUs are intentionally unsupported by tmux-trainsh.",
    ),
    FlashAttnCompatRule(
        rule_id="cuda_hopper_blackwell_fa4",
        backend="cuda",
        families=("hopper", "blackwell"),
        package_name="flash-attn-4",
        strategy="fa4",
        target="flash-attn-4",
        default_install_spec="flash-attn-4==4.0.0b5",
    ),
    FlashAttnCompatRule(
        rule_id="cuda_default_fa2",
        backend="cuda",
        families=("ampere", "ada", "hopper", "blackwell", "mixed", "", "unknown"),
        package_name="flash-attn",
        strategy="fa2",
        target="flash-attn 2.x",
        default_install_spec="flash-attn>=2,<3",
    ),
    FlashAttnCompatRule(
        rule_id="rocm_default_fa2",
        backend="rocm",
        families=("cdna", "mixed", "", "unknown"),
        package_name="flash-attn",
        strategy="fa2-rocm",
        target="flash-attn 2.x",
        default_install_spec="flash-attn>=2,<3",
    ),
)


__all__ = ["FLASH_ATTN_COMPAT_RULES", "FlashAttnCompatRule"]
