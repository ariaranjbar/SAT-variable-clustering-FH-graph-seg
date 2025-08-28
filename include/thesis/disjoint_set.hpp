#pragma once

#include <vector>
#include <cstddef>
#include <cassert>

namespace thesis {

// Disjoint-set (Union-Find) with union by rank and path compression.
// Optimized to track the number of connected components in O(1).
// Indices are 0..n-1.
class DisjointSets {
public:
    // Construct with n singleton sets.
    explicit DisjointSets(std::size_t n = 0);

    // Reset to n singleton sets, discarding previous state.
    void reset(std::size_t n);

    // Number of elements managed.
    std::size_t size() const { return parent_.size(); }

    // Find set representative with path compression.
    // Precondition: 0 <= x < size().
    unsigned find(unsigned x);

    // Find set representative without path compression (const, read-only traversal).
    // Precondition: 0 <= x < size().
    unsigned find_no_compress(unsigned x) const;

    // Union two sets, returning the resulting representative.
    // If already in the same set, returns the existing representative.
    // Precondition: 0 <= a,b < size().
    unsigned unite(unsigned a, unsigned b);

    // Whether two elements are in the same set.
    bool same(unsigned a, unsigned b) const { return find_no_compress(a) == find_no_compress(b); }

    // Current number of disjoint components.
    unsigned components() const { return comp_count_; }

    // Roots of the current forest
    std::vector<unsigned> roots() const;

private:
    std::vector<unsigned> parent_;
    std::vector<unsigned char> rank_; // 8-bit rank is typically sufficient
    unsigned comp_count_ = 0;
};

} // namespace thesis
