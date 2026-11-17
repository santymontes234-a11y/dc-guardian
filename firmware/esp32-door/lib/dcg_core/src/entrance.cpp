#include "entrance.h"

namespace dcg {

namespace {
inline bool reached(uint32_t now, uint32_t at) { return int32_t(now - at) >= 0; }
}  // namespace

void EntrancePoller::handle(const EntranceSignal& s) {
  if (s.id == lastId_) {
    hal_.log("entrance signal " + s.id + " already shown, ignored");
    return;
  }
  switch (s.result) {
    case EntranceResult::GRANTED:
      hal_.log("ENTRANCE QR GRANTED -> entrance LED " + std::to_string(s.ledMs) + " ms" +
               (s.displayName.empty() ? "" : " (" + s.displayName + ")"));
      hal_.onEntranceSignal(true, s.ledMs, s.displayName);
      break;
    case EntranceResult::DENIED:
      hal_.log("ENTRANCE QR DENIED");
      hal_.onEntranceSignal(false, 0, s.displayName);
      break;
    default:
      // Unknown result: ignored and logged, never acknowledged as shown.
      hal_.log("entrance signal with unknown result '" + s.rawResult + "' ignored");
      return;
  }
  lastId_ = s.id;
  ++shown_;
  ackId_ = s.id;
  ackAttempts_ = 0;
}

bool EntrancePoller::tick(uint32_t now, bool online) {
  if (!online) return false;
  if (started_ && !reached(now, nextMs_)) return false;
  started_ = true;
  nextMs_ = now + t_.pollMs;

  if (!ackId_.empty()) {  // the ack goes first, in its own tick
    ApiResult r = backend_.entranceAck(ackId_);
    if (r == ApiResult::OK || ++ackAttempts_ >= t_.ackMaxAttempts) {
      if (r != ApiResult::OK) hal_.log(std::string("giving up entrance ack: ") + apiResultName(r));
      ackId_.clear();
      ackAttempts_ = 0;
    }
    return true;
  }

  EntrancePollReply reply;
  ApiResult r = backend_.entrancePoll(reply);
  if (r != ApiResult::OK) {
    // Unsigned / bad signature / malformed / network: ignore completely (LED stays off).
    hal_.log(std::string("entrance poll failed: ") + apiResultName(r));
    nextMs_ = now + t_.errorBackoffMs;
    return true;
  }
  if (reply.hasSignal) handle(reply.signal);
  return true;
}

}  // namespace dcg
