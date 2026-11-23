#include "solver.hpp"

#include <algorithm>
#include <cassert>
#include <charconv>
#include <limits>
#include <new>
#include <stdexcept>
#include <utility>

namespace sat {
namespace {

int checkedNvars(int nvars) {
  if (nvars < 0) {
    throw std::invalid_argument("nvars must be non-negative");
  }
  return nvars;
}

Clause* newClause(size_t size) {
  assert(size > 0);
  void* memory = ::operator new(sizeof(Clause) + size * sizeof(Lit));
  Clause* clause = new (memory) Clause();
  clause->size = static_cast<uint32_t>(size);
  clause->lits =
      reinterpret_cast<Lit*>(reinterpret_cast<char*>(clause) + sizeof(Clause));
  return clause;
}

void deleteClause(Clause* clause) {
  clause->~Clause();
  ::operator delete(clause);
}

}  // namespace

const char* statusName(Status status) {
  switch (status) {
    case Status::Sat:
      return "SATISFIABLE";
    case Status::Unsat:
      return "UNSATISFIABLE";
    case Status::Unknown:
      return "UNKNOWN";
  }
  return "UNKNOWN";
}

Solver::Solver(int nvars, SolverOptions options)
    : nvars_(checkedNvars(nvars)),
      options_(std::move(options)),
      heuristic_(makeDecisionHeuristic(options_.heuristic, nvars_, options_.seed)),
      assigns_(static_cast<size_t>(nvars_), 0),
      phase_(static_cast<size_t>(nvars_), 0),
      level_(static_cast<size_t>(nvars_), 0),
      reason_(static_cast<size_t>(nvars_), nullptr),
      watches_(static_cast<size_t>(2) * static_cast<size_t>(nvars_)),
      seen_(static_cast<size_t>(nvars_), 0),
      lbd_stamp_(static_cast<size_t>(nvars_) + 1, 0) {
  if (options_.trace_stride == 0) {
    options_.trace_stride = 1;
  }
  trail_.reserve(nvars_);
  trail_lim_.reserve(nvars_);
  analyze_toclear_.reserve(nvars_);
  analyze_stack_.reserve(nvars_);
  learnt_clause_.reserve(nvars_);
  if (options_.trace) {
    openTrace();
  }
  if (options_.proof) {
    openProof();
    proof_buffer_.reserve(1 << 20);
  }
}

Solver::~Solver() {
  flushProof();
  for (Clause* clause : originals_) {
    deleteClause(clause);
  }
  for (Clause* clause : learnts_) {
    deleteClause(clause);
  }
}

int Solver::value(Lit p) const {
  int8_t a = assigns_[var(p)];
  if (a == 0) {
    return 0;
  }
  bool is_true = (a == 1) != sign(p);
  return is_true ? 1 : -1;
}

bool Solver::enqueue(Lit p, Clause* reason) {
  int v = var(p);
  int8_t wanted = sign(p) ? -1 : 1;
  if (assigns_[v] != 0) {
    return assigns_[v] == wanted;
  }
  assigns_[v] = wanted;
  level_[v] = decisionLevel();
  reason_[v] = reason;
  phase_[v] = wanted == 1 ? 1 : 0;
  trail_.push_back(p);
  heuristic_->assign(v);
  return true;
}

bool Solver::addClause(std::vector<Lit> lits) {
  if (!ok_) {
    return false;
  }

  std::vector<Lit> normalized;
  normalized.reserve(lits.size());
  for (Lit p : lits) {
    if (var(p) < 0 || var(p) >= nvars_) {
      error_ = "literal out of range";
      ok_ = false;
      return false;
    }
    bool duplicate = false;
    bool tautology = false;
    for (Lit q : normalized) {
      if (q == p) {
        duplicate = true;
        break;
      }
      if (q == neg(p)) {
        tautology = true;
        break;
      }
    }
    if (tautology) {
      return true;
    }
    if (!duplicate) {
      normalized.push_back(p);
    }
  }

  if (normalized.empty()) {
    ok_ = false;
    return false;
  }

  Clause* clause = newClause(normalized.size());
  clause->id = next_clause_id_++;
  std::copy(normalized.begin(), normalized.end(), clause->lits);
  originals_.push_back(clause);

  if (clause->size == 1) {
    if (!enqueue(clause->lits[0], clause)) {
      ok_ = false;
      return false;
    }
    return true;
  }

  attach(clause);
  return true;
}

void Solver::attach(Clause* clause) {
  assert(clause->size >= 2);
  watches_[clause->lits[0]].push_back(Watcher{clause, clause->lits[1]});
  watches_[clause->lits[1]].push_back(Watcher{clause, clause->lits[0]});
}

void Solver::detach(Clause* clause) {
  for (int i = 0; i < 2; ++i) {
    auto& ws = watches_[clause->lits[i]];
    for (size_t j = 0; j < ws.size(); ++j) {
      if (ws[j].clause == clause) {
        ws[j] = ws.back();
        ws.pop_back();
        break;
      }
    }
  }
}

Clause* Solver::propagate() {
  while (qhead_ < trail_.size()) {
    Lit p = trail_[qhead_++];
    ++stats_.propagations;
    Lit false_lit = neg(p);
    auto& ws = watches_[false_lit];
    size_t i = 0;
    size_t j = 0;

    while (i < ws.size()) {
      Watcher watcher = ws[i];
      Clause* clause = watcher.clause;

      if (value(watcher.blocker) == 1) {
        ws[j++] = watcher;
        ++i;
        continue;
      }

      if (clause->lits[0] == false_lit) {
        std::swap(clause->lits[0], clause->lits[1]);
      }
      assert(clause->lits[1] == false_lit);

      if (value(clause->lits[0]) == 1) {
        watcher.blocker = clause->lits[0];
        ws[j++] = watcher;
        ++i;
        continue;
      }

      bool moved = false;
      for (size_t k = 2; k < clause->size; ++k) {
        if (value(clause->lits[k]) != -1) {
          clause->lits[1] = clause->lits[k];
          clause->lits[k] = false_lit;
          watches_[clause->lits[1]].push_back(Watcher{clause, clause->lits[0]});
          moved = true;
          break;
        }
      }
      if (moved) {
        ++i;
        continue;
      }

      watcher.blocker = clause->lits[0];
      ws[j++] = watcher;
      ++i;

      if (value(clause->lits[0]) == -1) {
        while (i < ws.size()) {
          ws[j++] = ws[i++];
        }
        ws.resize(j);
        return clause;
      }

      if (!enqueue(clause->lits[0], clause)) {
        while (i < ws.size()) {
          ws[j++] = ws[i++];
        }
        ws.resize(j);
        return clause;
      }
    }
    ws.resize(j);
  }
  return nullptr;
}

void Solver::analyze(Clause* conflict, std::vector<Lit>& out, int& backtrack_level) {
  out.clear();
  out.push_back(kLitUndef);
  analyze_toclear_.clear();

  int path_count = 0;
  Lit p = kLitUndef;
  int index = static_cast<int>(trail_.size()) - 1;

  do {
    if (conflict == nullptr) {
      error_ = "conflict analysis reached a decision variable prematurely";
      break;
    }
    for (uint32_t literal_index = 0; literal_index < conflict->size; ++literal_index) {
      Lit q = conflict->lits[literal_index];
      if (q == p) {
        continue;
      }
      int v = var(q);
      if (!seen_[v] && level_[v] > 0) {
        seen_[v] = 1;
        analyze_toclear_.push_back(q);
        heuristic_->bump(v);
        if (level_[v] == decisionLevel()) {
          ++path_count;
        } else {
          out.push_back(q);
        }
      }
    }

    while (index >= 0 && !seen_[var(trail_[index])]) {
      --index;
    }
    if (index < 0) {
      error_ = "conflict analysis ran out of trail literals";
      break;
    }

    p = trail_[index--];
    seen_[var(p)] = 0;
    --path_count;
    conflict = reason_[var(p)];
  } while (path_count > 0);

  if (!error_.empty()) {
    for (Lit q : analyze_toclear_) {
      seen_[var(q)] = 0;
    }
    return;
  }

  out[0] = neg(p);

  if (out.size() > 1) {
    uint32_t abstract_levels = 0;
    for (size_t i = 1; i < out.size(); ++i) {
      abstract_levels |= 1u << (level_[var(out[i])] & 31);
    }

    size_t kept = 1;
    for (size_t i = 1; i < out.size(); ++i) {
      Lit q = out[i];
      if (reason_[var(q)] == nullptr || !litRedundant(q, abstract_levels)) {
        out[kept++] = q;
      }
    }
    out.resize(kept);

    size_t max_index = 1;
    for (size_t i = 2; i < out.size(); ++i) {
      if (level_[var(out[i])] > level_[var(out[max_index])]) {
        max_index = i;
      }
    }
    std::swap(out[1], out[max_index]);
    backtrack_level = level_[var(out[1])];
  } else {
    backtrack_level = 0;
  }

  ++lbd_epoch_;
  if (lbd_epoch_ == 0) {
    std::fill(lbd_stamp_.begin(), lbd_stamp_.end(), 0);
    lbd_epoch_ = 1;
  }
  uint32_t lbd = 0;
  for (Lit q : out) {
    int l = level_[var(q)];
    if (lbd_stamp_[static_cast<size_t>(l)] != lbd_epoch_) {
      lbd_stamp_[static_cast<size_t>(l)] = lbd_epoch_;
      ++lbd;
    }
  }
  last_lbd_ = lbd;

  for (Lit q : analyze_toclear_) {
    seen_[var(q)] = 0;
  }
}

bool Solver::litRedundant(Lit p, uint32_t abstract_levels) {
  analyze_stack_.clear();
  analyze_stack_.push_back(p);
  size_t top = analyze_toclear_.size();

  while (!analyze_stack_.empty()) {
    Lit q = analyze_stack_.back();
    analyze_stack_.pop_back();
    Clause* reason = reason_[var(q)];
    if (reason == nullptr) {
      for (size_t k = top; k < analyze_toclear_.size(); ++k) {
        seen_[var(analyze_toclear_[k])] = 0;
      }
      analyze_toclear_.resize(top);
      return false;
    }

    for (uint32_t literal_index = 0; literal_index < reason->size; ++literal_index) {
      Lit r = reason->lits[literal_index];
      if (r == q) {
        continue;
      }
      int v = var(r);
      if (!seen_[v] && level_[v] > 0) {
        if (reason_[v] != nullptr &&
            ((1u << (level_[v] & 31)) & abstract_levels) != 0) {
          seen_[v] = 1;
          analyze_toclear_.push_back(r);
          analyze_stack_.push_back(r);
        } else {
          for (size_t k = top; k < analyze_toclear_.size(); ++k) {
            seen_[var(analyze_toclear_[k])] = 0;
          }
          analyze_toclear_.resize(top);
          return false;
        }
      }
    }
  }
  return true;
}

void Solver::cancelUntil(int level) {
  if (decisionLevel() <= level) {
    return;
  }
  int first = trail_lim_[static_cast<size_t>(level)];
  for (int c = static_cast<int>(trail_.size()) - 1; c >= first; --c) {
    int v = var(trail_[static_cast<size_t>(c)]);
    assigns_[v] = 0;
    reason_[v] = nullptr;
    heuristic_->unassign(v);
  }
  qhead_ = static_cast<size_t>(first);
  trail_.resize(static_cast<size_t>(first));
  trail_lim_.resize(static_cast<size_t>(level));
}

void Solver::addLearnt(std::vector<Lit>& lits, int backtrack_level, uint32_t lbd) {
  writeProofClause(lits);
  if (!error_.empty()) {
    return;
  }
  cancelUntil(backtrack_level);

  if (lits.size() == 1) {
    ++stats_.learnts;
    if (!enqueue(lits[0], nullptr)) {
      ok_ = false;
    }
    return;
  }

  Clause* clause = newClause(lits.size());
  clause->id = next_clause_id_++;
  std::copy(lits.begin(), lits.end(), clause->lits);
  clause->lbd = lbd;
  clause->learnt = true;
  learnts_.push_back(clause);
  ++stats_.learnts;

  attach(clause);
  if (!enqueue(lits[0], clause)) {
    error_ = "asserting learned literal is already false";
    ok_ = false;
  }
  last_lbd_ = lbd;
}

bool Solver::isLocked(const Clause* clause) const {
  for (uint32_t literal_index = 0; literal_index < clause->size; ++literal_index) {
    Lit p = clause->lits[literal_index];
    if (value(p) == 1 && reason_[var(p)] == clause) {
      return true;
    }
  }
  return false;
}

void Solver::reduceDB() {
  ++stats_.reductions;

  std::vector<Clause*> candidates;
  candidates.reserve(learnts_.size());
  for (Clause* clause : learnts_) {
    if (clause->size <= 2 || clause->lbd <= 2) {
      continue;
    }
    if (isLocked(clause)) {
      continue;
    }
    candidates.push_back(clause);
  }

  size_t remove_count = candidates.size() / 2;
  if (remove_count == 0) {
    return;
  }

  std::sort(candidates.begin(), candidates.end(), [](const Clause* a, const Clause* b) {
    if (a->lbd != b->lbd) {
      return a->lbd > b->lbd;
    }
    if (a->size != b->size) {
      return a->size > b->size;
    }
    return a->id < b->id;
  });

  for (size_t i = 0; i < remove_count; ++i) {
    candidates[i]->deleted = true;
  }

  std::vector<Clause*> kept;
  kept.reserve(learnts_.size() - remove_count);
  for (Clause* clause : learnts_) {
    if (clause->deleted) {
      detach(clause);
      deleteClause(clause);
      ++stats_.deleted;
    } else {
      kept.push_back(clause);
    }
  }
  learnts_.swap(kept);
}

bool Solver::verifyModel() const {
  auto satisfies = [this](const Clause* clause) {
    for (uint32_t literal_index = 0; literal_index < clause->size; ++literal_index) {
      if (value(clause->lits[literal_index]) == 1) {
        return true;
      }
    }
    return false;
  };
  for (const Clause* clause : originals_) {
    if (!satisfies(clause)) {
      return false;
    }
  }
  for (const Clause* clause : learnts_) {
    if (!satisfies(clause)) {
      return false;
    }
  }
  return true;
}

uint64_t Solver::luby(uint64_t index) {
  uint64_t size = 1;
  uint64_t seq = 0;
  while (size < index + 1) {
    if (size > (std::numeric_limits<uint64_t>::max() - 1) / 2) {
      break;
    }
    ++seq;
    size = 2 * size + 1;
  }
  while (size - 1 != index) {
    size = (size - 1) >> 1;
    if (size == 0) {
      return 1;
    }
    --seq;
    index %= size;
  }
  return 1ULL << seq;
}

void Solver::openTrace() {
  trace_.open(options_.trace_path, std::ios::out | std::ios::trunc);
  if (!trace_) {
    throw std::runtime_error("cannot open trace file: " + options_.trace_path);
  }
  trace_ << "conflicts,level,trail,learnts,time_ms\n";
}

void Solver::traceRow() {
  if (!trace_.is_open()) {
    return;
  }
  double ms = std::chrono::duration<double, std::milli>(
                  std::chrono::steady_clock::now() - solve_start_)
                  .count();
  trace_ << stats_.conflicts << ',' << decisionLevel() << ',' << trail_.size()
         << ',' << learnts_.size() << ',' << ms << '\n';
}

void Solver::openProof() {
  proof_.open(options_.proof_path, std::ios::out | std::ios::trunc);
  if (!proof_) {
    throw std::runtime_error("cannot open DRAT proof file: " + options_.proof_path);
  }
}

void Solver::writeProofClause(const std::vector<Lit>& lits) {
  if (!proof_.is_open()) {
    return;
  }
  for (Lit p : lits) {
    int value = sign(p) ? -(var(p) + 1) : (var(p) + 1);
    char buffer[16];
    auto result = std::to_chars(buffer, buffer + sizeof(buffer), value);
    proof_buffer_.append(buffer, static_cast<size_t>(result.ptr - buffer));
    proof_buffer_.push_back(' ');
  }
  proof_buffer_ += "0\n";
  ++stats_.proof_clauses;
  if (proof_buffer_.size() >= (1u << 20)) {
    flushProof();
  }
}

void Solver::writeProofEmpty() {
  if (!proof_.is_open()) {
    return;
  }
  proof_buffer_ += "0\n";
  ++stats_.proof_clauses;
  flushProof();
}

void Solver::flushProof() {
  if (!proof_.is_open()) {
    return;
  }
  if (!proof_buffer_.empty()) {
    proof_ << proof_buffer_;
    proof_buffer_.clear();
  }
  proof_.flush();
  if (!proof_) {
    error_ = "failed to write DRAT proof";
  }
}

Status Solver::solve() {
  if (solved_) {
    return final_status_;
  }

  solve_start_ = std::chrono::steady_clock::now();
  auto finish = [this](Status status) {
    if (status == Status::Unsat && error_.empty()) {
      writeProofEmpty();
    }
    flushProof();
    if (options_.proof && !error_.empty()) {
      status = Status::Unknown;
    }
    stats_.seconds =
        std::chrono::duration<double>(std::chrono::steady_clock::now() - solve_start_)
            .count();
    final_status_ = status;
    solved_ = true;
    if (status == Status::Unsat) {
      ok_ = false;
    }
    if (trace_.is_open()) {
      trace_.flush();
    }
    return status;
  };

  if (!error_.empty()) {
    return finish(Status::Unknown);
  }
  if (!ok_) {
    return finish(Status::Unsat);
  }

  if (propagate() != nullptr) {
    return finish(Status::Unsat);
  }
  if (trace_.is_open()) {
    traceRow();
  }

  uint64_t conflicts_since_restart = 0;
  uint64_t restart_index = 0;
  uint64_t restart_limit = options_.restart_base > 0 ? options_.restart_base : 1;
  uint64_t next_reduce = options_.reduce_first;

  while (true) {
    Clause* conflict = propagate();

    if (conflict != nullptr) {
      ++stats_.conflicts;
      ++conflicts_since_restart;

      if (trace_.is_open() && stats_.conflicts % options_.trace_stride == 0) {
        traceRow();
      }

      if (decisionLevel() == 0) {
        return finish(Status::Unsat);
      }

      int backtrack_level = 0;
      analyze(conflict, learnt_clause_, backtrack_level);
      if (!error_.empty()) {
        return finish(Status::Unknown);
      }

      addLearnt(learnt_clause_, backtrack_level, last_lbd_);
      if (!error_.empty()) {
        return finish(Status::Unknown);
      }
      if (!ok_) {
        return finish(Status::Unsat);
      }

      heuristic_->onConflict();

      if (options_.reduce_db && stats_.conflicts >= next_reduce) {
        reduceDB();
        next_reduce = stats_.conflicts + options_.reduce_first +
                      options_.reduce_inc * stats_.reductions;
      }

      if (options_.restarts && conflicts_since_restart >= restart_limit) {
        cancelUntil(0);
        ++stats_.restarts;
        conflicts_since_restart = 0;
        ++restart_index;
        restart_limit = options_.restart_base * luby(restart_index);
        if (restart_limit == 0) {
          restart_limit = 1;
        }
      }
    } else {
      int v = heuristic_->pick();
      if (v < 0) {
        model_.assign(static_cast<size_t>(nvars_), 0);
        for (int i = 0; i < nvars_; ++i) {
          model_[static_cast<size_t>(i)] = assigns_[static_cast<size_t>(i)];
        }
        if (!verifyModel()) {
          error_ = "internal model check failed";
          return finish(Status::Unknown);
        }
        return finish(Status::Sat);
      }
      ++stats_.decisions;
      trail_lim_.push_back(static_cast<int>(trail_.size()));
      enqueue(mkLit(v, phase_[static_cast<size_t>(v)] == 0), nullptr);
    }
  }
}

}  // namespace sat
