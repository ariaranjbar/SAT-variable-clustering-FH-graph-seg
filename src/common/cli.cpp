#include "thesis/cli.hpp"
#include <charconv>
#include <stdexcept>

namespace thesis {

long long parse_int64(const std::string& s, long long minVal, long long maxVal) {
    long long value = 0;
    const char* begin = s.data();
    const char* end = s.data() + s.size();
    auto [ptr, ec] = std::from_chars(begin, end, value);
    if (ec != std::errc{} || ptr != end) {
        throw std::invalid_argument("invalid integer: " + s);
    }
    if (value < minVal || value > maxVal) {
        throw std::out_of_range("value out of range");
    }
    return value;
}

}
