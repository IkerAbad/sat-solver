#include <cstdint>
#include <cstdlib>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <random>
#include <string>
#include <vector>

#include "dimacs.hpp"
#include "generators.hpp"
#include "solver.hpp"

namespace {

int failures = 0;

void expect(bool condition, const std::string& message) {
  if (!condition) {
    std::cerr << "FAIL: " << message << '\n';
    ++failures;
  }
}

sat::Lit litFromDimacs(int value) {
  int variable = value < 0 ? -value : value;
  return sat::mkLit(variable - 1, value < 0);
}

bool clauseSatisfied(const std::vector<sat::Lit>& clause,
                     const std::vector<int8_t>& model) {
  for (sat::Lit p : clause) {
    int8_t value = model[static_cast<size_t>(sat::var(p))];
    bool positive = value > 0;
    if (positive != sat::sign(p)) {
      return true;
    }
  }
  return false;
}

bool modelSatisfies(int nvars, const std::vector<std::vector<sat::Lit>>& clauses,
                    const std::vector<int8_t>& model) {
  if (static_cast<int>(model.size()) != nvars) {
    return false;
  }
  for (int8_t value : model) {
    if (value == 0) {
      return false;
    }
  }
  for (const auto& clause : clauses) {
    if (!clauseSatisfied(clause, model)) {
      return false;
    }
  }
  return true;
}

bool bruteForceSat(int nvars, const std::vector<std::vector<sat::Lit>>& clauses) {
  if (nvars > 24) {
    return false;
  }
  const uint64_t total = 1ULL << nvars;
  for (uint64_t mask = 0; mask < total; ++mask) {
    bool all = true;
    for (const auto& clause : clauses) {
      bool satisfied = false;
      for (sat::Lit p : clause) {
        bool value = (mask >> sat::var(p)) & 1ULL;
        if (value != sat::sign(p)) {
          satisfied = true;
          break;
        }
      }
      if (!satisfied) {
        all = false;
        break;
      }
    }
    if (all) {
      return true;
    }
  }
  return false;
}

sat::Status solveCnf(int nvars, const std::vector<std::vector<sat::Lit>>& clauses,
                     const sat::SolverOptions& options,
                     std::vector<int8_t>& model) {
  sat::Solver solver(nvars, options);
  for (const auto& clause : clauses) {
    if (!solver.addClause(clause)) {
      break;
    }
  }
  sat::Status status = solver.solve();
  if (status == sat::Status::Sat) {
    model = solver.model();
  }
  return status;
}

void testBasic() {
  {
    std::vector<int8_t> model;
    auto status = solveCnf(0, {}, {}, model);
    expect(status == sat::Status::Sat, "empty formula is SAT");
    expect(model.empty(), "empty formula has empty model");
  }
  {
    std::vector<int8_t> model;
    auto status = solveCnf(1, {{}}, {}, model);
    expect(status == sat::Status::Unsat, "empty clause is UNSAT");
  }
  {
    std::vector<int8_t> model;
    auto status = solveCnf(1, {{litFromDimacs(1)}, {litFromDimacs(-1)}}, {}, model);
    expect(status == sat::Status::Unsat, "contradictory units are UNSAT");
  }
  {
    std::vector<int8_t> model;
    auto status = solveCnf(2,
                           {{litFromDimacs(1), litFromDimacs(2)},
                            {litFromDimacs(-1), litFromDimacs(2)}},
                           {}, model);
    expect(status == sat::Status::Sat, "two-clause formula is SAT");
    expect(modelSatisfies(2,
                          {{litFromDimacs(1), litFromDimacs(2)},
                           {litFromDimacs(-1), litFromDimacs(2)}},
                          model),
           "model satisfies two-clause formula");
  }
  {
    std::vector<std::vector<sat::Lit>> clauses;
    for (int mask = 0; mask < 8; ++mask) {
      std::vector<sat::Lit> clause;
      for (int v = 0; v < 3; ++v) {
        clause.push_back(litFromDimacs((mask & (1 << v)) ? -(v + 1) : (v + 1)));
      }
      clauses.push_back(std::move(clause));
    }
    std::vector<int8_t> model;
    auto status = solveCnf(3, clauses, {}, model);
    expect(status == sat::Status::Unsat, "all 3-variable clauses are UNSAT");
  }
}

void testGenerators() {
  {
    sat::GeneratedInstance php = sat::generatePigeonhole(4, 3);
    std::vector<std::vector<sat::Lit>> clauses = php.clauses;
    std::vector<int8_t> model;
    auto status = solveCnf(php.nvars, clauses, {}, model);
    expect(status == sat::Status::Unsat, "pigeonhole 4 into 3 is UNSAT");
  }
  {
    sat::GeneratedInstance php = sat::generatePigeonhole(3, 3);
    std::vector<int8_t> model;
    auto status = solveCnf(php.nvars, php.clauses, {}, model);
    expect(status == sat::Status::Sat, "pigeonhole 3 into 3 is SAT");
    expect(modelSatisfies(php.nvars, php.clauses, model),
           "pigeonhole 3 into 3 model is valid");
  }
  {
    sat::GeneratedInstance coloring = sat::generateColoring(12, 3, 0.35, 77, true);
    std::vector<int8_t> model;
    auto status = solveCnf(coloring.nvars, coloring.clauses, {}, model);
    expect(status == sat::Status::Sat, "planted 3-coloring is SAT");
    expect(modelSatisfies(coloring.nvars, coloring.clauses, model),
           "planted coloring model is valid");
  }
}

void testFuzz() {
  std::mt19937_64 rng(0x123456789abcdefULL);

  std::vector<sat::SolverOptions> option_sets;
  {
    sat::SolverOptions options;
    option_sets.push_back(options);
  }
  for (sat::HeuristicKind kind :
       {sat::HeuristicKind::Vmtf, sat::HeuristicKind::Random}) {
    sat::SolverOptions options;
    options.heuristic = kind;
    options.seed = 42;
    option_sets.push_back(options);
  }
  {
    sat::SolverOptions options;
    options.restart_base = 1;
    options.reduce_first = 5;
    options.reduce_inc = 5;
    option_sets.push_back(options);
  }
  {
    sat::SolverOptions options;
    options.restarts = false;
    options.reduce_db = false;
    options.heuristic = sat::HeuristicKind::Random;
    options.seed = 7;
    option_sets.push_back(options);
  }

  for (int iteration = 0; iteration < 250; ++iteration) {
    int nvars = 1 + static_cast<int>(rng() % 12);
    int nclauses = static_cast<int>(rng() % (6 * nvars + 2));
    std::vector<std::vector<sat::Lit>> clauses;
    clauses.reserve(static_cast<size_t>(nclauses));
    for (int c = 0; c < nclauses; ++c) {
      int size = static_cast<int>(rng() % 5);
      std::vector<sat::Lit> clause;
      clause.reserve(static_cast<size_t>(size));
      for (int k = 0; k < size; ++k) {
        int v = static_cast<int>(rng() % static_cast<uint64_t>(nvars));
        clause.push_back(sat::mkLit(v, (rng() & 1) != 0));
      }
      clauses.push_back(std::move(clause));
    }

    bool expected = bruteForceSat(nvars, clauses);
    for (size_t set = 0; set < option_sets.size(); ++set) {
      std::vector<int8_t> model;
      sat::Status status = solveCnf(nvars, clauses, option_sets[set], model);
      if (expected) {
        expect(status == sat::Status::Sat,
               "fuzz iteration " + std::to_string(iteration) + " set " +
                   std::to_string(set) + " expected SAT");
        if (status == sat::Status::Sat) {
          expect(modelSatisfies(nvars, clauses, model),
                 "fuzz iteration " + std::to_string(iteration) + " set " +
                     std::to_string(set) + " model invalid");
        }
      } else {
        expect(status == sat::Status::Unsat,
               "fuzz iteration " + std::to_string(iteration) + " set " +
                   std::to_string(set) + " expected UNSAT");
      }
      if (failures > 20) {
        return;
      }
    }
  }
}

void testProof() {
  std::filesystem::path proof_path =
      std::filesystem::temp_directory_path() / "satsolver_proof_test.drat";
  std::filesystem::remove(proof_path);

  sat::GeneratedInstance php = sat::generatePigeonhole(4, 3);
  {
    sat::SolverOptions options;
    options.proof = true;
    options.proof_path = proof_path.string();
    sat::Solver solver(php.nvars, options);
    for (const auto& clause : php.clauses) {
      solver.addClause(clause);
    }
    sat::Status status = solver.solve();
    expect(status == sat::Status::Unsat, "proof test formula is UNSAT");
    expect(solver.stats().proof_clauses > 0, "proof test emitted clauses");
  }

  std::ifstream proof(proof_path);
  expect(proof.good(), "proof file exists");
  std::string line;
  std::string last_nonempty;
  int lines = 0;
  while (std::getline(proof, line)) {
    if (!line.empty()) {
      last_nonempty = line;
      ++lines;
    }
  }
  proof.close();
  expect(lines > 0, "proof file is not empty");
  expect(last_nonempty == "0", "proof file ends with the empty clause");
  std::filesystem::remove(proof_path);
}

void testParser() {
  std::filesystem::path path =
      std::filesystem::temp_directory_path() / "satsolver_parser_test.cnf";
  {
    std::ofstream output(path);
    output << "c leading comment\n"
           << "p cnf 3 2\n"
           << "1 -2 0\n"
           << "c between clauses\n"
           << "2 3 0\n";
  }

  sat::Formula formula;
  std::string error;
  bool parsed = sat::parseDimacs(path.string(), formula, error);
  expect(parsed, "DIMACS parser accepts a valid file: " + error);
  expect(formula.nvars == 3, "DIMACS parser reads the variable count");
  expect(formula.clauses.size() == 2, "DIMACS parser reads the clause count");
  if (formula.clauses.size() == 2) {
    expect(formula.clauses[0][0] == litFromDimacs(1), "DIMACS first literal");
    expect(formula.clauses[0][1] == litFromDimacs(-2), "DIMACS negative literal");
  }

  std::filesystem::path out =
      std::filesystem::temp_directory_path() / "satsolver_writer_test.cnf";
  sat::Formula written;
  written.nvars = 2;
  written.clauses = {{litFromDimacs(1), litFromDimacs(-2)}};
  expect(sat::writeDimacs(out.string(), written, {"test"}, error),
         "DIMACS writer succeeds: " + error);
  sat::Formula reread;
  expect(sat::parseDimacs(out.string(), reread, error),
         "DIMACS writer output parses: " + error);
  expect(reread.nvars == 2 && reread.clauses.size() == 1,
         "DIMACS round trip dimensions");

  std::filesystem::remove(path);
  std::filesystem::remove(out);
}

}  // namespace

int main() {
  testBasic();
  testGenerators();
  testFuzz();
  testProof();
  testParser();

  if (failures != 0) {
    std::cerr << failures << " test failure(s)\n";
    return 1;
  }
  std::cout << "all tests passed\n";
  return 0;
}
