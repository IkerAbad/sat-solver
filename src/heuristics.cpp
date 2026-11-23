#include "heuristics.hpp"

#include <algorithm>
#include <cassert>
#include <limits>

namespace sat {
namespace {

constexpr double kActivityRescale = 1e100;
constexpr double kActivityScaleDown = 1e-100;
constexpr double kVsidsDecay = 0.95;

class Vsids final : public DecisionHeuristic {
public:
  Vsids(int nvars, uint64_t /*seed*/) : nvars_(nvars), activity_(nvars, 0.0), pos_(nvars, -1) {
    heap_.reserve(nvars);
    for (int v = 0; v < nvars_; ++v) {
      insert(v);
    }
  }

  void assign(int v) override { remove(v); }

  void unassign(int v) override {
    if (pos_[v] < 0) {
      insert(v);
    }
  }

  void bump(int v) override {
    activity_[v] += inc_;
    if (activity_[v] > kActivityRescale) {
      rescale();
    }
    if (pos_[v] >= 0) {
      siftUp(pos_[v]);
    }
  }

  void onConflict() override {
    inc_ *= 1.0 / kVsidsDecay;
    if (inc_ > kActivityRescale) {
      rescale();
    }
  }

  int pick() override { return heap_.empty() ? -1 : heap_.front(); }

private:
  bool better(int a, int b) const {
    if (activity_[a] != activity_[b]) {
      return activity_[a] > activity_[b];
    }
    return a < b;
  }

  void insert(int v) {
    assert(pos_[v] < 0);
    pos_[v] = static_cast<int>(heap_.size());
    heap_.push_back(v);
    siftUp(pos_[v]);
  }

  void remove(int v) {
    int i = pos_[v];
    if (i < 0) {
      return;
    }
    int last = heap_.back();
    heap_.pop_back();
    pos_[v] = -1;
    if (i < static_cast<int>(heap_.size())) {
      heap_[i] = last;
      pos_[last] = i;
      siftUp(i);
      siftDown(i);
    }
  }

  void siftUp(int i) {
    int v = heap_[i];
    while (i > 0) {
      int parent = (i - 1) / 2;
      if (!better(v, heap_[parent])) {
        break;
      }
      heap_[i] = heap_[parent];
      pos_[heap_[i]] = i;
      i = parent;
    }
    heap_[i] = v;
    pos_[v] = i;
  }

  void siftDown(int i) {
    int v = heap_[i];
    int n = static_cast<int>(heap_.size());
    while (true) {
      int left = 2 * i + 1;
      if (left >= n) {
        break;
      }
      int right = left + 1;
      int best = left;
      if (right < n && better(heap_[right], heap_[left])) {
        best = right;
      }
      if (!better(heap_[best], v)) {
        break;
      }
      heap_[i] = heap_[best];
      pos_[heap_[i]] = i;
      i = best;
    }
    heap_[i] = v;
    pos_[v] = i;
  }

  void rescale() {
    for (double& a : activity_) {
      a *= kActivityScaleDown;
    }
    inc_ *= kActivityScaleDown;
  }

  int nvars_;
  std::vector<double> activity_;
  std::vector<int> heap_;
  std::vector<int> pos_;
  double inc_ = 1.0;
};

// Move-to-front order over all variables. Variables bumped during conflict
// analysis move to the front, including variables that are still assigned;
// decisions scan from the front for the first unassigned variable.
class Vmtf final : public DecisionHeuristic {
public:
  Vmtf(int nvars, uint64_t /*seed*/)
      : prev_(nvars, -1), next_(nvars, -1), assigned_(nvars, 0) {
    for (int v = nvars - 1; v >= 0; --v) {
      next_[v] = head_;
      if (head_ >= 0) {
        prev_[head_] = v;
      }
      head_ = v;
    }
  }

  void assign(int v) override { assigned_[v] = 1; }
  void unassign(int v) override { assigned_[v] = 0; }

  void bump(int v) override {
    if (head_ == v) {
      return;
    }
    if (prev_[v] >= 0) {
      next_[prev_[v]] = next_[v];
    }
    if (next_[v] >= 0) {
      prev_[next_[v]] = prev_[v];
    }
    prev_[v] = -1;
    next_[v] = head_;
    if (head_ >= 0) {
      prev_[head_] = v;
    }
    head_ = v;
  }

  int pick() override {
    for (int v = head_; v >= 0; v = next_[v]) {
      if (!assigned_[v]) {
        return v;
      }
    }
    return -1;
  }

private:
  std::vector<int> prev_;
  std::vector<int> next_;
  std::vector<uint8_t> assigned_;
  int head_ = -1;
};

class Random final : public DecisionHeuristic {
public:
  Random(int nvars, uint64_t seed) : pos_(nvars, -1) {
    vars_.reserve(nvars);
    for (int v = 0; v < nvars; ++v) {
      pos_[v] = v;
      vars_.push_back(v);
    }
    state_ = seed != 0 ? seed : 0x9e3779b97f4a7c15ULL;
  }

  void assign(int v) override {
    int i = pos_[v];
    if (i < 0) {
      return;
    }
    int last = vars_.back();
    vars_[i] = last;
    pos_[last] = i;
    vars_.pop_back();
    pos_[v] = -1;
  }

  void unassign(int v) override {
    if (pos_[v] >= 0) {
      return;
    }
    pos_[v] = static_cast<int>(vars_.size());
    vars_.push_back(v);
  }

  void bump(int /*v*/) override {}

  int pick() override {
    if (vars_.empty()) {
      return -1;
    }
    return vars_[nextRandom() % vars_.size()];
  }

private:
  uint64_t nextRandom() {
    uint64_t x = state_;
    x ^= x >> 12;
    x ^= x << 25;
    x ^= x >> 27;
    state_ = x;
    return x * 2685821657736338717ULL;
  }

  std::vector<int> vars_;
  std::vector<int> pos_;
  uint64_t state_ = 0;
};

}  // namespace

bool parseHeuristic(const std::string& text, HeuristicKind& out) {
  if (text == "vsids") {
    out = HeuristicKind::Vsids;
    return true;
  }
  if (text == "vmtf") {
    out = HeuristicKind::Vmtf;
    return true;
  }
  if (text == "random") {
    out = HeuristicKind::Random;
    return true;
  }
  return false;
}

const char* heuristicName(HeuristicKind kind) {
  switch (kind) {
    case HeuristicKind::Vsids:
      return "vsids";
    case HeuristicKind::Vmtf:
      return "vmtf";
    case HeuristicKind::Random:
      return "random";
  }
  return "unknown";
}

std::unique_ptr<DecisionHeuristic> makeDecisionHeuristic(HeuristicKind kind,
                                                        int nvars,
                                                        uint64_t seed) {
  switch (kind) {
    case HeuristicKind::Vsids:
      return std::make_unique<Vsids>(nvars, seed);
    case HeuristicKind::Vmtf:
      return std::make_unique<Vmtf>(nvars, seed);
    case HeuristicKind::Random:
      return std::make_unique<Random>(nvars, seed);
  }
  return nullptr;
}

}  // namespace sat
