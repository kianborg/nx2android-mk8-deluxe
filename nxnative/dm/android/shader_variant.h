// Distinct bits for independent runtime SPIR-V variants and their cache keys.
#pragma once
enum {
    VK_SHADER_FRAG_DEPTH = 1,
    VK_SHADER_DUAL_SOURCE = 2,
    VK_SHADER_CLIP_DEPTH = 4,
};
static inline int vk_shader_variant_flags(int stage, int writes_depth, int flags) {
    if (stage == 1) return (flags & VK_SHADER_DUAL_SOURCE) | (writes_depth ? 0 : flags & VK_SHADER_FRAG_DEPTH);
    if (stage == 0 || stage == 2) return flags & VK_SHADER_CLIP_DEPTH;
    return 0;
}
