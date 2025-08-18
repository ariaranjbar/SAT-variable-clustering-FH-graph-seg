#pragma once
#include <cstddef>
#include <string>

namespace thesis {

// Utility to parse an integer from a string with bounds checking.
// Throws std::invalid_argument or std::out_of_range on error.
long long parse_int64(const std::string& s, long long minVal, long long maxVal);

}
