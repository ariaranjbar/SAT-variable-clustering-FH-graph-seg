#pragma once
#include <chrono>
#include <cstdint>

namespace thesis {

class Timer {
public:
    using clock = std::chrono::high_resolution_clock;

    Timer() { reset(); }

    void reset() { start_ = clock::now(); }

    // Returns elapsed milliseconds as double
    double ms() const {
        return std::chrono::duration<double, std::milli>(clock::now() - start_).count();
    }

    // Returns elapsed seconds as double
    double sec() const {
        return std::chrono::duration<double>(clock::now() - start_).count();
    }

private:
    clock::time_point start_{};
};

} // namespace thesis
