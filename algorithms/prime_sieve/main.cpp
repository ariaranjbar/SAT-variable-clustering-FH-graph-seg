#include <iostream>
#include <vector>
#include <string>
#include <stdexcept>
#include <cmath>
#include <algorithm>
#include "thesis/timer.hpp"
#include "thesis/cli.hpp"

static std::vector<int> sieve(int64_t n) {
    if (n < 2) return {};
    std::vector<bool> is_prime(n + 1, true);
    is_prime[0] = is_prime[1] = false;
    for (int64_t p = 2; p * p <= n; ++p) {
        if (is_prime[p]) {
            for (int64_t q = p * p; q <= n; q += p) is_prime[q] = false;
        }
    }
    std::vector<int> primes;
    primes.reserve(static_cast<size_t>(n / std::max<int64_t>(1, std::log(n))));
    for (int64_t i = 2; i <= n; ++i) if (is_prime[i]) primes.push_back(static_cast<int>(i));
    return primes;
}

int main(int argc, char** argv) {
    int64_t n = 10'000'000; // default
    if (argc > 1) {
        try {
            n = thesis::parse_int64(argv[1], 2, 200'000'000);
        } catch (const std::exception& e) {
            std::cerr << "Usage: prime_sieve [n<=200000000]" << " (" << e.what() << ")" << std::endl;
            return 1;
        }
    }

    thesis::Timer t;
    auto primes = sieve(n);
    double ms = t.ms();

    std::cout << "n=" << n << ", primes=" << primes.size() << ", time_ms=" << ms;
    if (!primes.empty()) std::cout << ", last=" << primes.back();
    std::cout << std::endl;
    return 0;
}
