#include <vector>
#include <cstdint>
#include <numeric>
#include <limits>
#include "thesis/vig.hpp"

using Edge = thesis::Edge;

// Compute modularity Q for an undirected, weighted graph represented as a list of edges
// (each undirected edge appears once with u < v). Communities are given by comm_of(v).
// Uses the standard Newman–Girvan/Blondel form:
//   Q = sum_c [ (Σ_in(c) / m) - gamma * (Σ_tot(c) / (2m))^2 ]
// where m = sum of edge weights (each undirected edge counted once),
// Σ_in(c) = sum of weights of edges inside community c (each undirected edge counted once),
// Σ_tot(c) = sum of weighted degrees of vertices in community c.
template <typename CommFn>
double modularity(
    uint32_t n,
    const std::vector<Edge>& edges,
    CommFn&& comm_of,
    double gamma = 1.0
) {
  if (n == 0) return 0.0;

  // strengths (degrees) k_i and total edge weight m
  std::vector<double> k(n, 0.0);
  double m = 0.0; // sum of weights over undirected edges
  for (const auto& e : edges) {
    k[e.u] += e.w;
    k[e.v] += e.w;
    m += e.w;
  }
  if (m == 0.0) return 0.0; // no edges → define Q = 0
  const double two_m = 2.0 * m;

  // Build community labels and compress to [0..C)
  std::vector<int> comm(n);
  int max_label = -1;
  for (uint32_t v = 0; v < n; ++v) {
    int cv = static_cast<int>(comm_of(v));
    comm[v] = cv;
    if (cv > max_label) max_label = cv;
  }
  int C = 0;
  std::vector<int> remap(static_cast<size_t>(std::max<int>(max_label + 1, static_cast<int>(n))), -1);
  for (uint32_t v = 0; v < n; ++v) {
    int lbl = comm[v];
    if (lbl < 0) continue; // ignore invalid
    if (lbl >= static_cast<int>(remap.size())) {
      remap.resize(static_cast<size_t>(lbl + 1), -1);
    }
    if (remap[lbl] == -1) remap[lbl] = C++;
  }
  if (C == 0) return 0.0;

  // Accumulate Σ_tot(c) and Σ_in(c)
  std::vector<double> sum_tot(static_cast<size_t>(C), 0.0);
  std::vector<double> sum_in(static_cast<size_t>(C), 0.0);

  for (uint32_t v = 0; v < n; ++v) {
    int lbl = comm[v];
    if (lbl < 0) continue;
    int cid = remap[lbl];
    if (cid >= 0) sum_tot[static_cast<size_t>(cid)] += k[v];
  }

  for (const auto& e : edges) {
    int cu = remap[comm[e.u]];
    int cv = remap[comm[e.v]];
    if (cu >= 0 && cu == cv) {
      // Each undirected internal edge counted once
      sum_in[static_cast<size_t>(cu)] += e.w;
    }
  }

  // Q = sum_c [ (Σ_in(c) / m) - gamma * (Σ_tot(c) / (2m))^2 ]
  double Q = 0.0;
  for (int c = 0; c < C; ++c) {
    const double in_c = sum_in[static_cast<size_t>(c)];
    const double tot_c = sum_tot[static_cast<size_t>(c)];
    Q += (in_c / m) - gamma * (tot_c / two_m) * (tot_c / two_m);
  }
  return Q;
}