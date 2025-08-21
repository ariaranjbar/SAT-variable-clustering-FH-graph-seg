#include "thesis/segmentation.hpp"
#include <numeric>

namespace thesis {

GraphSegmenterFH::GraphSegmenterFH(unsigned n, double k) { reset(n, k); }

void GraphSegmenterFH::reset(unsigned n, double k) {
    dsu_.reset(n);
    comp_size_.assign(n, 1);
    min_sim_.assign(n, std::numeric_limits<double>::infinity());
    k_ = k;
}

static inline bool edge_desc(const SegEdge& a, const SegEdge& b) { return a.w > b.w; }

void GraphSegmenterFH::run(std::vector<SegEdge>& edges) {
    std::sort(edges.begin(), edges.end(), edge_desc);
    for (const auto& e : edges) {
        unsigned a = dsu_.find(e.u);
        unsigned b = dsu_.find(e.v);
        if (a == b) continue;
        const double gate_a = gate(a);
        const double gate_b = gate(b);
        if (e.w >= (gate_a > gate_b ? gate_a : gate_b)) {
            // unite returns new representative; we need to merge sizes and min-sim
            unsigned ra = a, rb = b;
            // Determine which representative will be the parent by consulting union-by-rank inside dsu
            // We can't peek rank; instead, call unite and map old to new rep
            unsigned r = dsu_.unite(a, b);
            unsigned child = (r == a ? b : a);
            comp_size_[r] = comp_size_[a] + comp_size_[b];
            // Track minimal similarity within the component
            double prev_min = std::min(min_sim_[a], min_sim_[b]);
            min_sim_[r] = std::min(prev_min, e.w);
            // Optionally clear child's stats (not necessary functionally)
            // comp_size_[child] = 0; // keep for potential debug
            // min_sim_[child] = min_sim_[r];
        }
    }
}

double GraphSegmenterFH::gate(unsigned r) const {
    const double inv_min = std::isinf(min_sim_[r]) ? 0.0 : (1.0 / min_sim_[r]);
    const double tau = k_ / static_cast<double>(comp_size_[r]);
    const double denom = inv_min + tau;
    return (denom == 0.0) ? std::numeric_limits<double>::infinity() : (1.0 / denom);
}

} // namespace thesis
