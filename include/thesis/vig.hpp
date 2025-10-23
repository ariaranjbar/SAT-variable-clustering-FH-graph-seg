#pragma once

#include <cstdint>
#include <vector>
#include <limits>
#include <cstddef>
#include "thesis/cnf.hpp"
#include <assert.h>
#include <cmath>

namespace thesis
{

  // ------------------------------------------------------------------
  // Weighting policy: pair weight w_α(s) = 2 * s^{-α} / (s-1), s>=2.
  // α = 1 reproduces existing behavior (each clause contributes total mass 1).
  // ------------------------------------------------------------------
  struct Weighting
  {
    double alpha{1.0};
    inline double pair_weight(std::size_t s) const
    {
      if (s < 2) return 0.0;
      return 2.0 * std::pow(static_cast<double>(s), -alpha) / static_cast<double>(s - 1);
    }
  };

  // Pick α from (tau, eps) ensuring (tau/2)^{1-α} <= eps.
  // Special cases:
  //   tau <= 2 -> α = 1.
  //   tau == max (treated as "infinite") -> α = 1 to preserve legacy behavior.
  inline double pick_alpha_tau_only(unsigned tau, double eps)
  {
    if (tau <= 2) return 1.0;
    if (tau == std::numeric_limits<unsigned>::max()) return 1.0; // treat as infinite cutoff
    const double ratio = static_cast<double>(tau) / 2.0;
    if (ratio <= 1.0) return 1.0; // defensive
    double a = 1.0 - std::log(eps) / std::log(ratio);
    if (a < 1.0) a = 1.0; // clamp
    return a;
  }

  struct Edge
  {
    uint32_t u; // 0-based variable id, canonical u < v
    uint32_t v; // 0-based variable id
    double w;   // aggregated weight
  };

  struct VIG
  {
    uint32_t n{0};
    std::vector<Edge> edges;
    size_t aggregation_memory{0};
  };

  // Build VIG by aggregating over clause variable pairs.
  VIG build_vig_naive(const CNF &cnf,
                      unsigned clause_size_threshold = std::numeric_limits<unsigned>::max());

  // Optimized/batched variant with fixed buffer capacity in number of (a,b,w) triples.
  VIG build_vig_optimized(const CNF &cnf,
                          unsigned clause_size_threshold,
                          std::size_t max_buffer_contributions);

  VIG build_vig_optimized(const CNF &cnf,
                          unsigned clause_size_threshold,
                          std::size_t max_buffer_contributions,
                          unsigned num_threads);

} // namespace thesis
