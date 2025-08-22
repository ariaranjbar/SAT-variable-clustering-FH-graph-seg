#pragma once
// Compact metrics for distributions of component sizes produced by graph segmentation.
//
// This header provides:
//  - CompSummary: small set of scale-free metrics that capture balance of component sizes.
//  - component_sizes: counts nodes per component id into a compact sizes vector.
//  - summarize_components: computes metrics from the sizes vector.
//
// Design goals:
//  - Header-only counting (component_sizes) to avoid virtual/interface overhead in hot loops.
//  - No external dependencies. C++17-compatible.
//  - Robust to arbitrary labels (sparse, non-contiguous, zero-based recommended).
//  - Time: O(N + K log K), Memory: O(N) worst-case for counting array.

#include <vector>
#include <cstdint>

namespace thesis {

/**
 * Summary of component size distribution.
 *
 * Fields:
 *  - K: number of non-empty components (sizes.size()).
 *  - N: total number of nodes (sum of sizes, clamped to uint32_t max).
 *  - keff: effective number of components (Hill number, order 2), 1 / sum p_i^2.
 *  - gini: Gini coefficient in [0,1] over component sizes (0=perfectly balanced).
 *  - pmax: share of the largest component, max_i p_i where p_i = sizes[i]/N.
 *  - entropyJ: entropy evenness in [0,1] = H / ln(K), where H = -sum p_i ln p_i; define 1 when K<=1.
 */
struct CompSummary {
    uint32_t K = 0;
    uint32_t N = 0;
    double keff = 0.0;
    double gini = 0.0;
    double pmax = 0.0;
    double entropyJ = 1.0;
};

/**
 * Count component sizes from node-to-component labels.
 *
 * @tparam GetComponent callable with signature uint32_t(uint32_t v)
 * @param N number of nodes (labels are queried for v in [0, N)).
 * @param get_component function to map node index -> component/root id (zero-based; need not be contiguous).
 * @return vector of nonzero component sizes (one entry per non-empty label).
 *
 * Details:
 *  - Internally resizes a counting array to accommodate the largest observed label.
 *  - Produces a compact vector with only nonzero counts, preserving no particular order.
 *  - Works with sparse labels (e.g., DSU roots).
 *
 * Complexity: O(N) time, O(R) memory where R = 1 + max(label), worst-case O(N).
 */
template <class GetComponent>
std::vector<uint32_t> component_sizes(uint32_t N, GetComponent&& get_component) {
    std::vector<uint32_t> counts;
    counts.reserve(N);
    uint32_t max_label = 0;
    for (uint32_t v = 0; v < N; ++v) {
        uint32_t r = get_component(v);
        if (r >= counts.size()) counts.resize(static_cast<size_t>(r) + 1u, 0u);
        ++counts[r];
        if (r > max_label) max_label = r;
    }
    std::vector<uint32_t> sizes;
    sizes.reserve(max_label + 1u);
    for (uint32_t r = 0; r < counts.size(); ++r) if (counts[r] != 0u) sizes.push_back(counts[r]);
    return sizes;
}

/**
 * Compute compact summary metrics from a vector of component sizes.
 *
 * Let S = sum sizes, K = sizes.size(), p_i = sizes[i] / S.
 *  - keff:   if S>0 then 1 / sum_i p_i^2 else 0.
 *  - gini:   sort asc x_(i); G = (2 * sum_{i=1..K} i * x_(i)) / (K * S) - (K + 1) / K; clamp to [0,1].
 *  - pmax:   max_i p_i (0 if K==0).
 *  - entropyJ: if K<=1 then 1; else ( -sum p_i ln p_i ) / ln(K), ignoring p_i=0.
 *
 * Edge cases:
 *  - K==0 or S==0: keff=0, gini=0, pmax=0, entropyJ=1 (by convention).
 *  - K==1: gini=0, entropyJ=1.
 *
 * Complexity: O(K log K) due to sorting for Gini; others are O(K).
 */
CompSummary summarize_components(const std::vector<uint32_t>& sizes);

} // namespace thesis
