#pragma once

#include <algorithm>
#include <cstddef>
#include <cstdint>
#include <limits>
#include <utility>
#include <vector>
#include <unordered_map>

#include "thesis/disjoint_set.hpp"
#include "thesis/vig.hpp" // for Edge (u,v,w)

namespace thesis {

// Edge with similarity weight (larger = more similar)
using SegEdge = thesis::Edge;

// Graph segmentation based on Felzenszwalb-Huttenlocher predicate.
// Uses union-find with union-by-rank and path compression.
// Gate(C) = max_dist(C) + k/|C|
class GraphSegmenterFH {
public:
    // Construct a segmenter for n nodes and parameter k.
    explicit GraphSegmenterFH(unsigned n = 0, double k = 50.0);

    // Reset to n nodes, clearing any previous state.
    void reset(unsigned n, double k);

    // Run segmentation in-place on the provided edges.
    // Edges will be sorted descending by weight.
    void run(std::vector<SegEdge>& edges);

    // After run(), compute strongest inter-component edges.
    // Returns one edge per unordered pair of components (u,v) with maximum similarity weight.
    // The endpoints u,v are component representatives (roots) at the end of segmentation.
    // If there is no edge between two components in the input, it won't appear in the result.
    std::vector<SegEdge> strongest_inter_component_edges() const;

    // Access the non-union edges that connect two different components at the
    // time they were considered (i.e., potential inter-component connections).
    // Stored in the same descending order used during segmentation.
    const std::vector<SegEdge>& inter_component_candidates() const { return inter_comp_candidates_; }

    // Accessors
    unsigned node_count() const { return static_cast<unsigned>(comp_size_.size()); }
    unsigned num_components() const { return dsu_.components(); }

    // Representative/root id for x (0..n-1). Non-const compressing find.
    unsigned component(unsigned x) { return dsu_.find(x); }
    // Const variant without compression.
    unsigned component_no_compress(unsigned x) const { return dsu_.find_no_compress(x); }

    // Size of the component whose representative is r.
    unsigned comp_size(unsigned r) const { return comp_size_[r]; }

    // Minimum similarity weight observed within the component (representative r).
    double comp_min_weight(unsigned r) const { return 1.0/max_dist_[r]; }

private:
    double gate(unsigned r) const;

    static inline std::uint64_t pair_key(unsigned a, unsigned b) {
        if (a > b) std::swap(a, b);
        return (static_cast<std::uint64_t>(a) << 32) | static_cast<std::uint64_t>(b);
    }

    DisjointSets dsu_{};
    std::vector<unsigned> comp_size_{};
    std::vector<double> max_dist_{};
    double k_ = 50.0;
    // Non-union edges that were cross-component when processed (descending weight order).
    // These are candidates for strongest inter-component connections.
    std::vector<SegEdge> inter_comp_candidates_{};
};

} // namespace thesis
