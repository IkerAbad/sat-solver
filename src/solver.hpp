#pragma once

#include <chrono>
#include <cstdint>
#include <fstream>
#include <memory>
#include <string>
#include <vector>

#include "heuristics.hpp"

namespace sat {

using Lit = int32_t;
constexpr Lit kLitUndef = -1;

inline int var(Lit p) { return p >> 1; }
inline bool sign(Lit p) { return (p & 1) != 0; }
inline Lit mkLit(int v, bool negative = false) {
  return static_cast<Lit>((v << 1) | (negative ? 1 : 0));
}
inline Lit neg(Lit p) { return p ^ 1; }

struct Clause {
  std::vector<Lit> lits;
  uint64_t id = 0;
  uint32_t lbd = 0;
  bool learnt = false;
  bool deleted = false;
};

struct Watcher {
  Clause* clause = nullptr;
  Lit blocker = kLitUndef;
};

struct SolverOptions {
  HeuristicKind heuristic = HeuristicKind::Vsids;
  bool restarts = true;
  uint64_t restart_base = 100;
  bool reduce_db = true;
  uint64_t reduce_first = 2000;
  uint64_t reduce_inc = 300;
  uint64_t seed = 0x243f6a8885a308d3ULL;
  bool trace = false;
  std::string trace_path;
  uint64_t trace_stride = 1;
};

struct SolverStats {
  uint64_t conflicts = 0;
  uint64_t decisions = 0;
  uint64_t propagations = 0;
  uint64_t restarts = 0;
  uint64_t learnts = 0;
  uint64_t deleted = 0;
  uint64_t reductions = 0;
  double seconds = 0.0;
};

enum class Status { Sat, Unsat, Unknown };

const char* statusName(Status status);

class Solver {
public:
  explicit Solver(int nvars, SolverOptions options = {});
  ~Solver();

  Solver(const Solver&) = delete;
  Solver& operator=(const Solver&) = delete;

  // Adds a clause over variables [0, nvars). Returns false if the formula is
  // already known to be unsatisfiable. A tautological clause is ignored.
  bool addClause(std::vector<Lit> lits);

  Status solve();

  int nvars() const { return nvars_; }
  const std::vector<int8_t>& model() const { return model_; }
  const SolverStats& stats() const { return stats_; }
  const std::string& error() const { return error_; }

private:
  int decisionLevel() const { return static_cast<int>(trail_lim_.size()); }
  int value(Lit p) const;
  bool enqueue(Lit p, Clause* reason);
  Clause* propagate();
  void analyze(Clause* conflict, std::vector<Lit>& out, int& backtrack_level);
  bool litRedundant(Lit p, uint32_t abstract_levels);
  void cancelUntil(int level);
  void addLearnt(std::vector<Lit>& lits, int backtrack_level, uint32_t lbd);
  void reduceDB();
  bool isLocked(const Clause* clause) const;
  bool verifyModel() const;
  void attach(Clause* clause);
  void detach(Clause* clause);

  static uint64_t luby(uint64_t index);
  void openTrace();
  void traceRow();

  int nvars_;
  SolverOptions options_;
  std::unique_ptr<DecisionHeuristic> heuristic_;

  std::vector<int8_t> assigns_;  // -1 false, 0 unassigned, +1 true
  std::vector<uint8_t> phase_;   // saved phase: 1 means try positive
  std::vector<int> level_;
  std::vector<Clause*> reason_;
  std::vector<Lit> trail_;
  std::vector<int> trail_lim_;
  size_t qhead_ = 0;

  std::vector<std::vector<Watcher>> watches_;
  std::vector<Clause*> originals_;
  std::vector<Clause*> learnts_;

  std::vector<uint8_t> seen_;
  std::vector<Lit> analyze_toclear_;
  std::vector<Lit> analyze_stack_;
  std::vector<Lit> learnt_clause_;
  std::vector<uint32_t> lbd_stamp_;
  uint32_t lbd_epoch_ = 0;
  uint32_t last_lbd_ = 0;

  uint64_t next_clause_id_ = 1;
  SolverStats stats_;
  std::vector<int8_t> model_;
  std::string error_;
  bool ok_ = true;
  bool solved_ = false;
  Status final_status_ = Status::Unknown;

  std::ofstream trace_;
  std::chrono::steady_clock::time_point solve_start_;
};

}  // namespace sat
