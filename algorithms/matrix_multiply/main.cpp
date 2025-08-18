#include <iostream>
#include <random>
#include <vector>
#include <string>
#include <stdexcept>
#include "thesis/timer.hpp"
#include "thesis/cli.hpp"

static std::vector<double> mul(const std::vector<double>& A, const std::vector<double>& B, int n) {
    std::vector<double> C(n * n, 0.0);
    for (int i = 0; i < n; ++i) {
        for (int k = 0; k < n; ++k) {
            double aik = A[i * n + k];
            for (int j = 0; j < n; ++j) {
                C[i * n + j] += aik * B[k * n + j];
            }
        }
    }
    return C;
}

int main(int argc, char** argv) {
    int n = 256; // default size
    if (argc > 1) {
        try {
            n = static_cast<int>(thesis::parse_int64(argv[1], 1, 4096));
        } catch (const std::exception& e) {
            std::cerr << "Usage: matrix_multiply [n<=4096]" << " (" << e.what() << ")" << std::endl;
            return 1;
        }
    }

    std::mt19937_64 rng(42);
    std::uniform_real_distribution<double> dist(-1.0, 1.0);

    std::vector<double> A(n * n), B(n * n);
    for (auto& v : A) v = dist(rng);
    for (auto& v : B) v = dist(rng);

    thesis::Timer t;
    auto C = mul(A, B, n);
    double ms = t.ms();

    // checksum to prevent optimization
    double sum = 0.0;
    for (double x : C) sum += x;

    std::cout << "n=" << n << ", time_ms=" << ms << ", checksum=" << sum << std::endl;
    return 0;
}
