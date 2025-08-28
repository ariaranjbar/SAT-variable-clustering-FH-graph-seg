#pragma once

#include <cstdint>
#include <vector>
#include <limits>
#include <cstddef>
#include "thesis/cnf.hpp"
#include <assert.h>

namespace thesis
{

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


#define WEIGHTED 0
#define UNWEIGHTED 1

namespace Louvain
{
  using namespace std;
  class Graph
  {
  public:
    unsigned int nb_nodes;
    unsigned long nb_links;
    double total_weight;

    vector<unsigned long> degrees;
    vector<unsigned int> links;
    vector<float> weights;

    Graph();

    Graph(int nb_nodes, int nb_links, double total_weight,
        std::vector<unsigned long> degrees,
        std::vector<unsigned int> links,
        std::vector<float> weights);

    bool check_symmetry();

    // return the number of neighbors (degree) of the node
    inline unsigned int nb_neighbors(unsigned int node);

    // return the number of self loops of the node
    inline double nb_selfloops(unsigned int node);

    // return the weighted degree of the node
    inline double weighted_degree(unsigned int node);

    // return pointers to the first neighbor and first weight of the node
    inline pair<vector<unsigned int>::iterator, vector<float>::iterator> neighbors(unsigned int node);
  };

  inline unsigned int
  Graph::nb_neighbors(unsigned int node)
  {
    assert(node >= 0 && node < nb_nodes);

    if (node == 0)
      return degrees[0];
    else
      return degrees[node] - degrees[node - 1];
  }

  inline double
  Graph::nb_selfloops(unsigned int node)
  {
    assert(node >= 0 && node < nb_nodes);

    pair<vector<unsigned int>::iterator, vector<float>::iterator> p = neighbors(node);
    for (unsigned int i = 0; i < nb_neighbors(node); i++)
    {
      if (*(p.first + i) == node)
      {
        if (weights.size() != 0)
          return (double)*(p.second + i);
        else
          return 1.;
      }
    }
    return 0.;
  }

  inline double
  Graph::weighted_degree(unsigned int node)
  {
    assert(node >= 0 && node < nb_nodes);

    if (weights.size() == 0)
      return (double)nb_neighbors(node);
    else
    {
      pair<vector<unsigned int>::iterator, vector<float>::iterator> p = neighbors(node);
      double res = 0;
      for (unsigned int i = 0; i < nb_neighbors(node); i++)
      {
        res += (double)*(p.second + i);
      }
      return res;
    }
  }

  inline pair<vector<unsigned int>::iterator, vector<float>::iterator>
  Graph::neighbors(unsigned int node)
  {
    assert(node >= 0 && node < nb_nodes);

    if (node == 0)
      return make_pair(links.begin(), weights.begin());
    else if (weights.size() != 0)
      return make_pair(links.begin() + degrees[node - 1], weights.begin() + degrees[node - 1]);
    else
      return make_pair(links.begin() + degrees[node - 1], weights.begin());
  }

  Graph build_graph(const thesis::CNF &cnf,
                    unsigned clause_size_threshold);
} // namespace Louvain