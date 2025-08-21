#include "thesis/disjoint_set.hpp"

namespace thesis {

DisjointSets::DisjointSets(std::size_t n) {
    reset(n);
}

void DisjointSets::reset(std::size_t n) {
    parent_.resize(n);
    rank_.assign(n, 0);
    comp_count_ = static_cast<unsigned>(n);
    for (unsigned i = 0; i < n; ++i) parent_[i] = i;
}

unsigned DisjointSets::find(unsigned x) {
    // Iterative path compression to avoid deep recursion
    unsigned root = x;
    while (root < parent_.size() && parent_[root] != root) {
        root = parent_[root];
    }
    // Path compression
    while (x < parent_.size() && parent_[x] != x) {
        unsigned p = parent_[x];
        parent_[x] = root;
        x = p;
    }
    return root;
}

unsigned DisjointSets::find_no_compress(unsigned x) const {
    unsigned root = x;
    while (root < parent_.size() && parent_[root] != root) {
        root = parent_[root];
    }
    return root;
}

unsigned DisjointSets::unite(unsigned a, unsigned b) {
    unsigned ra = find(a);
    unsigned rb = find(b);
    if (ra == rb) return ra;
    // union by rank
    if (rank_[ra] < rank_[rb]) {
        parent_[ra] = rb;
        --comp_count_;
        return rb;
    } else if (rank_[ra] > rank_[rb]) {
        parent_[rb] = ra;
        --comp_count_;
        return ra;
    } else {
        parent_[rb] = ra;
        ++rank_[ra];
        --comp_count_;
        return ra;
    }
}

} // namespace thesis
