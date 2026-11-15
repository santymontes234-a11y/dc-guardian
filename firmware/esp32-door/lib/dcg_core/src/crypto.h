// SHA-256 / HMAC-SHA256 helpers.
// On the ESP32 they use mbedTLS (hardware-accelerated); on the PC (native tests)
// a small portable implementation, so the same code paths are tested.
#pragma once

#include <cstddef>
#include <cstdint>
#include <string>

namespace dcg {

constexpr size_t kSha256Len = 32;

void sha256(const uint8_t* data, size_t len, uint8_t out[kSha256Len]);
void hmacSha256(const uint8_t* key, size_t keyLen, const uint8_t* msg, size_t msgLen,
                uint8_t out[kSha256Len]);

std::string toHex(const uint8_t* data, size_t len);  // lowercase
std::string sha256Hex(const std::string& data);
std::string hmacSha256Hex(const std::string& key, const std::string& msg);

// Compares two hex strings case-insensitively in constant time (for equal lengths).
bool hexEqualsConstantTime(const std::string& a, const std::string& b);

}  // namespace dcg
