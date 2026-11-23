#include <cstdlib>
#include <exception>
#include <iomanip>
#include <iostream>
#include <string>
#include <vector>

#include "dimacs.hpp"
#include "solver.hpp"

namespace {

void printUsage(const char* program) {
  std::cout
      << "Usage: " << program << " [options] <formula.cnf>\n\n"
      << "Options:\n"
      << "  --heuristic=vsids|vmtf|random  decision heuristic (default: vsids)\n"
      << "  --no-restarts                  disable Luby restarts\n"
      << "  --restart-base=N               base restart interval (default: 100)\n"
      << "  --no-reduce                    disable learned-clause reduction\n"
      << "  --reduce-first=N               first reduction conflict (default: 2000)\n"
      << "  --reduce-inc=N                 reduction interval growth (default: 300)\n"
      << "  --seed=N                       seed for the random heuristic\n"
      << "  --trace=FILE                   write conflict trace CSV\n"
      << "  --trace-stride=N               write every N-th conflict (default: 1)\n"
      << "  --help                         show this help\n";
}

uint64_t parseU64(const std::string& text, const std::string& option) {
  size_t consumed = 0;
  unsigned long long value = 0;
  try {
    value = std::stoull(text, &consumed, 10);
  } catch (const std::exception&) {
    throw std::runtime_error("invalid value for " + option + ": " + text);
  }
  if (consumed != text.size()) {
    throw std::runtime_error("invalid value for " + option + ": " + text);
  }
  return static_cast<uint64_t>(value);
}

}  // namespace

int main(int argc, char** argv) {
  sat::SolverOptions options;
  std::string input_path;
  std::string heuristic_text;

  try {
    for (int i = 1; i < argc; ++i) {
      std::string arg = argv[i];
      if (arg == "--help" || arg == "-h") {
        printUsage(argv[0]);
        return 0;
      }
      if (arg == "--no-restarts") {
        options.restarts = false;
        continue;
      }
      if (arg == "--no-reduce") {
        options.reduce_db = false;
        continue;
      }
      if (arg.rfind("--", 0) != 0) {
        if (!input_path.empty()) {
          throw std::runtime_error("more than one input file given");
        }
        input_path = arg;
        continue;
      }

      std::string key = arg;
      std::string value;
      size_t equal = arg.find('=');
      if (equal != std::string::npos) {
        key = arg.substr(0, equal);
        value = arg.substr(equal + 1);
      }
      auto takeValue = [&]() {
        if (!value.empty()) {
          return value;
        }
        if (i + 1 >= argc) {
          throw std::runtime_error("missing value for " + key);
        }
        return std::string(argv[++i]);
      };

      if (key == "--heuristic") {
        heuristic_text = takeValue();
      } else if (key == "--restart-base") {
        options.restart_base = parseU64(takeValue(), key);
      } else if (key == "--reduce-first") {
        options.reduce_first = parseU64(takeValue(), key);
      } else if (key == "--reduce-inc") {
        options.reduce_inc = parseU64(takeValue(), key);
      } else if (key == "--seed") {
        options.seed = parseU64(takeValue(), key);
      } else if (key == "--trace") {
        options.trace = true;
        options.trace_path = takeValue();
      } else if (key == "--trace-stride") {
        options.trace_stride = parseU64(takeValue(), key);
      } else {
        throw std::runtime_error("unknown option: " + key);
      }
    }

    if (input_path.empty()) {
      printUsage(argv[0]);
      return 1;
    }
    if (!heuristic_text.empty()) {
      if (!sat::parseHeuristic(heuristic_text, options.heuristic)) {
        throw std::runtime_error("unknown heuristic: " + heuristic_text);
      }
    }
    if (options.restart_base == 0) {
      throw std::runtime_error("--restart-base must be positive");
    }
    if (options.reduce_first == 0) {
      throw std::runtime_error("--reduce-first must be positive");
    }
  } catch (const std::exception& ex) {
    std::cerr << "error: " << ex.what() << '\n';
    return 1;
  }

  sat::Formula formula;
  std::string error;
  if (!sat::parseDimacs(input_path, formula, error)) {
    std::cerr << "error: " << error << '\n';
    return 1;
  }

  try {
    sat::Solver solver(formula.nvars, options);
    bool added = true;
    for (const auto& clause : formula.clauses) {
      if (!solver.addClause(clause)) {
        added = false;
        break;
      }
    }
    if (!added && !solver.error().empty()) {
      std::cerr << "error: " << solver.error() << '\n';
      return 1;
    }

    sat::Status status = solver.solve();
    const sat::SolverStats& stats = solver.stats();

    std::cout << "c satsolver 1.0.0\n";
    std::cout << "c heuristic " << sat::heuristicName(options.heuristic) << '\n';
    std::cout << "c vars " << formula.nvars << '\n';
    std::cout << "c clauses " << formula.clauses.size() << '\n';
    std::cout << "c conflicts " << stats.conflicts << '\n';
    std::cout << "c decisions " << stats.decisions << '\n';
    std::cout << "c propagations " << stats.propagations << '\n';
    std::cout << "c restarts " << stats.restarts << '\n';
    std::cout << "c learnts " << stats.learnts << '\n';
    std::cout << "c deleted " << stats.deleted << '\n';
    std::cout << "c reductions " << stats.reductions << '\n';
    std::cout << "c time " << std::fixed << std::setprecision(6) << stats.seconds << '\n';

    if (status == sat::Status::Sat) {
      std::cout << "s SATISFIABLE\n";
      std::cout << 'v';
      int printed = 0;
      for (int v = 0; v < formula.nvars; ++v) {
        int8_t value = solver.model()[static_cast<size_t>(v)];
        if (value == 0) {
          std::cerr << "error: model has an unassigned variable\n";
          return 1;
        }
        std::cout << ' ' << (value > 0 ? v + 1 : -(v + 1));
        ++printed;
        if (printed % 20 == 0) {
          std::cout << "\nv";
        }
      }
      std::cout << " 0\n";
      return 10;
    }
    if (status == sat::Status::Unsat) {
      std::cout << "s UNSATISFIABLE\n";
      return 20;
    }

    std::cout << "s UNKNOWN\n";
    if (!solver.error().empty()) {
      std::cout << "c error " << solver.error() << '\n';
    }
    return 1;
  } catch (const std::exception& ex) {
    std::cerr << "error: " << ex.what() << '\n';
    return 1;
  }
}
