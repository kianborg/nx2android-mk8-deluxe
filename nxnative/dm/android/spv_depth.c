#include "spv_depth.h"
#include <stdlib.h>
#include <string.h>

static uint32_t find_decl(const uint32_t *w, uint32_t end, uint32_t op, const uint32_t *args, uint32_t n) {
    for (uint32_t i = 5; i < end; i += w[i] >> 16)
        if ((w[i] & 65535) == op && w[i] >> 16 == n + 2 && !memcmp(w + i + 2, args, n * 4)) return w[i + 1];
    return 0;
}
static uint32_t find_constant(const uint32_t *w, uint32_t end, uint32_t type, uint32_t value) {
    for (uint32_t i = 5; i < end; i += w[i] >> 16)
        if ((w[i] & 65535) == 43 && w[i] >> 16 == 4 && w[i + 1] == type && w[i + 3] == value) return w[i + 2];
    return 0;
}
uint32_t *vk_spv_depth_remap(const uint32_t *w, uint32_t nw, uint32_t *onw) {
    if (!w || !onw || nw < 5 || w[0] != 0x07230203 || !w[3] || w[3] > 1048576) return NULL;
    *onw = 0;
    uint32_t fn = nw, entry = 0, model = ~0u, pos = 0, structure = 0, member = 0;
    uint32_t *at = calloc(w[3], sizeof *at); if (!at) return NULL;
    for (uint32_t i = 5; i < nw;) {
        uint32_t n = w[i] >> 16, op = w[i] & 65535;
        if (!n || n > nw - i) goto fail;
        if (op == 15) { // one OpEntryPoint
            if (entry || n < 4) goto fail;
            model = w[i + 1]; entry = w[i + 2];
        }
        if (op == 54 && fn == nw) fn = i;
        if (i < fn) {
            if (((op >= 19 && op <= 39) && n >= 2)) {
                if (w[i + 1] >= w[3]) goto fail;
                at[w[i + 1]] = i;
            } else if ((op == 59 || op == 43) && n >= 4) {
                if (w[i + 2] >= w[3]) goto fail;
                at[w[i + 2]] = i;
            }
            if (op == 71 && n == 4 && w[i + 2] == 11 && w[i + 3] == 0) pos = w[i + 1]; // BuiltIn Position

        }
        i += n;
    }
    if (!entry || fn == nw || (model != 0 && model != 2 && model != 3)) goto fail;
    uint32_t vec = 0;
    if (!pos) {
        for (uint32_t i = 5; i < fn; i += w[i] >> 16) if ((w[i] & 65535) == 59 && w[i] >> 16 >= 4 && w[i + 3] == 3) {
            uint32_t t = w[i + 1];
            if (t >= w[3] || !at[t]) continue;
            uint32_t p = at[t];
            if ((w[p] & 65535) != 32 || w[p] >> 16 != 4 || w[p + 2] != 3) continue;
            // Geometry modules have input and output gl_PerVertex structs. Only
            // the struct reached through this Output variable is a candidate.
            for (uint32_t j = 5; j < fn; j += w[j] >> 16)
                if ((w[j] & 65535) == 72 && w[j] >> 16 == 5 && w[j + 1] == w[p + 3] && w[j + 3] == 11 && w[j + 4] == 0) {
                    structure = w[j + 1]; member = w[j + 2]; pos = w[i + 2]; break;
                }
            if (pos) break;
        }
        if (!pos || !structure || structure >= w[3] || !at[structure]) goto fail;
        uint32_t s = at[structure];
        if ((w[s] & 65535) != 30 || member >= (w[s] >> 16) - 2) goto fail;
        vec = w[s + 2 + member];
    } else if (pos) {
        // A directly decorated output vec4, as emitted by the bundled translator.
        structure = 0;
    }
    if (!pos || pos >= w[3] || !at[pos]) goto fail;
    uint32_t v = at[pos];
    if ((w[v] & 65535) != 59 || w[v] >> 16 < 4 || w[v + 3] != 3 || w[v + 1] >= w[3]) goto fail;
    uint32_t p = at[w[v + 1]];
    if (!p || (w[p] & 65535) != 32 || w[p] >> 16 != 4 || w[p + 2] != 3) goto fail;
    if (!structure) vec = w[p + 3];
    if (vec >= w[3] || !at[vec]) goto fail;
    uint32_t vt = at[vec];
    if ((w[vt] & 65535) != 23 || w[vt] >> 16 != 4 || w[vt + 3] != 4) goto fail;
    uint32_t f32 = w[vt + 2];
    if (f32 >= w[3] || !at[f32] || (w[at[f32]] & 65535) != 22 || w[at[f32]] >> 16 != 3 || w[at[f32] + 2] != 32) goto fail;
    uint32_t bound = w[3], decl[32], nd = 0;
    uint32_t half = find_constant(w, fn, f32, 0x3f000000); // float 0.5
    if (!half) { half = bound++; uint32_t x[] = {4u << 16 | 43, f32, half, 0x3f000000}; memcpy(decl + nd, x, sizeof x); nd += 4; }
    uint32_t pointer = 0, index = 0;
    if (structure) {
        uint32_t pa[] = {3, vec}; pointer = find_decl(w, fn, 32, pa, 2);
        if (!pointer) { pointer = bound++; uint32_t x[] = {4u << 16 | 32, pointer, 3, vec}; memcpy(decl + nd, x, sizeof x); nd += 4; }
        uint32_t ia[] = {32, 0}, integer = find_decl(w, fn, 21, ia, 2);
        if (!integer) { integer = bound++; uint32_t x[] = {4u << 16 | 21, integer, 32, 0}; memcpy(decl + nd, x, sizeof x); nd += 4; }
        index = find_constant(w, fn, integer, member);
        if (!index) { index = bound++; uint32_t x[] = {4u << 16 | 43, integer, index, member}; memcpy(decl + nd, x, sizeof x); nd += 4; }
    }
    uint32_t sites = 0, function = 0;
    for (uint32_t i = fn; i < nw; i += w[i] >> 16) {
        uint32_t op = w[i] & 65535;
        if (op == 54) { if (w[i] >> 16 < 5) goto fail; function = w[i + 2]; }
        if (model == 3 ? (op == 218 || op == 220) : (function == entry && op == 253)) sites++;
    }
    if (!sites || (uint64_t)nw + nd + (uint64_t)sites * 46 > UINT32_MAX) goto fail;
    uint32_t *out = malloc(((size_t)nw + nd + (size_t)sites * 46) * 4); if (!out) goto fail;
    memcpy(out, w, fn * 4); memcpy(out + fn, decl, nd * 4); uint32_t no = fn + nd;
    function = 0;
    for (uint32_t i = fn; i < nw; i += w[i] >> 16) {
        uint32_t n = w[i] >> 16, op = w[i] & 65535;
        if (op == 54) function = w[i + 2];
        int inject = model == 3 ? (op == 218 || op == 220) : (function == entry && op == 253);
        uint32_t ptr = pos, original = 0;
        if (inject) {
            if (structure) { ptr = bound++; uint32_t x[] = {5u << 16 | 65, pointer, ptr, pos, index}; memcpy(out + no, x, sizeof x); no += 5; }
            original = bound++; uint32_t z = bound++, ww = bound++, zh = bound++, wh = bound++, zz = bound++, result = bound++;
            uint32_t x[] = {
                4u << 16 | 61, vec, original, ptr,
                5u << 16 | 81, f32, z, original, 2,
                5u << 16 | 81, f32, ww, original, 3,
                5u << 16 | 133, f32, zh, z, half,
                5u << 16 | 133, f32, wh, ww, half,
                5u << 16 | 129, f32, zz, zh, wh,
                6u << 16 | 82, vec, result, zz, original, 2,
                3u << 16 | 62, ptr, result};
            memcpy(out + no, x, sizeof x); no += sizeof x / 4;
        }
        memcpy(out + no, w + i, n * 4); no += n;
        // EmitVertex makes outputs undefined; restoring the original avoids
        // converting z twice when a geometry shader reuses the same position.
        if (inject && model == 3) { uint32_t x[] = {3u << 16 | 62, ptr, original}; memcpy(out + no, x, sizeof x); no += 3; }
    }
    out[3] = bound; *onw = no; free(at); return out;
fail:
    free(at); return NULL;
}
