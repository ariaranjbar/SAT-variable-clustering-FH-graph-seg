#include "thesis/segmentation.hpp"
#include <numeric>

namespace thesis {

GraphSegmenterFH::GraphSegmenterFH(unsigned n, double k) { reset(n, k); }

void GraphSegmenterFH::reset(unsigned n, double k) {
    dsu_.reset(n);
    comp_size_.assign(n, 1);
    max_dist_.assign(n, 0);
    k_ = k;
}

static inline bool edge_desc(const SegEdge& a, const SegEdge& b) { return a.w > b.w; }

void GraphSegmenterFH::run(std::vector<SegEdge>& edges) {
    std::sort(edges.begin(), edges.end(), edge_desc);
    for (const auto& e : edges) {
        unsigned a = dsu_.find(e.u);
        unsigned b = dsu_.find(e.v);
        if (a == b) continue;
        const double connection_distance = 1/e.w;
        const double gate_a = gate(a);
        const double gate_b = gate(b);
        if (connection_distance <= (gate_a < gate_b ? gate_a : gate_b)) {
            // unite returns new representative; we need to merge sizes and min-sim
            // Determine which representative will be the parent by consulting union-by-rank inside dsu
            unsigned r = dsu_.unite(a, b);
            comp_size_[r] = comp_size_[a] + comp_size_[b];
            // Track maximum distance within the component (use connection_distance)
            double prev_max = std::max(max_dist_[a], max_dist_[b]);
            max_dist_[r] = std::max(prev_max, connection_distance);
        }
    }
}

double GraphSegmenterFH::gate(unsigned r) const {
    const double tau = k_ / static_cast<double>(comp_size_[r]);
    return max_dist_[r] + tau;

}

} // namespace thesis
