#pragma once

#include <cstdint>
#include <vector>
#include <limits>
#include <cstddef>
#include "thesis/cnf.hpp"

namespace thesis {

struct Edge {
  uint32_t u; // 0-based variable id, canonical u < v
  uint32_t v; // 0-based variable id
  double   w; // aggregated weight
};

struct VIG {
  uint32_t n{0};
  std::vector<Edge> edges;
  size_t aggregation_memory{0};
};

// Build VIG by aggregating over clause variable pairs.
VIG build_vig_naive(const CNF& cnf,
                    unsigned clause_size_threshold = std::numeric_limits<unsigned>::max(),
                    bool sort_descending_by_weight = true);

// Optimized/batched variant with fixed buffer capacity in number of (a,b,w) triples.
VIG build_vig_optimized(const CNF& cnf,
                        unsigned clause_size_threshold,
                        std::size_t max_buffer_contributions,
                        bool sort_descending_by_weight = true);

} // namespace thesis
