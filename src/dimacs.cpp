#include "dimacs.hpp"

#include <fstream>
#include <sstream>
#include <string>

namespace sat {

bool parseDimacs(const std::string& path, Formula& formula, std::string& error) {
  std::ifstream input(path);
  if (!input) {
    error = "cannot open file: " + path;
    return false;
  }

  std::string line;
  std::string data;
  while (std::getline(input, line)) {
    size_t first = line.find_first_not_of(" \t\r");
    if (first == std::string::npos) {
      continue;
    }
    if (line[first] == 'c') {
      continue;
    }
    data += line;
    data += '\n';
  }

  std::istringstream stream(data);
  std::string token;
  if (!(stream >> token) || token != "p") {
    error = "missing DIMACS problem line";
    return false;
  }

  std::string format;
  long long nvars = 0;
  long long nclauses = 0;
  if (!(stream >> format >> nvars >> nclauses) || format != "cnf") {
    error = "invalid DIMACS header";
    return false;
  }
  if (nvars < 0 || nvars > 100000000LL || nclauses < 0) {
    error = "invalid DIMACS dimensions";
    return false;
  }

  formula.nvars = static_cast<int>(nvars);
  formula.clauses.clear();
  formula.clauses.reserve(static_cast<size_t>(nclauses));

  std::vector<Lit> current;
  long long parsed_clauses = 0;
  while (stream >> token) {
    if (token == "%") {
      break;
    }
    int literal = 0;
    try {
      size_t consumed = 0;
      literal = std::stoi(token, &consumed);
      if (consumed != token.size()) {
        error = "invalid integer token: " + token;
        return false;
      }
    } catch (const std::exception&) {
      error = "invalid integer token: " + token;
      return false;
    }

    if (literal == 0) {
      formula.clauses.push_back(current);
      current.clear();
      ++parsed_clauses;
      continue;
    }

    long long variable = literal < 0 ? -static_cast<long long>(literal) : literal;
    if (variable < 1 || variable > nvars) {
      error = "literal out of range: " + token;
      return false;
    }
    current.push_back(mkLit(static_cast<int>(variable) - 1, literal < 0));
  }

  if (!current.empty()) {
    error = "unterminated clause at end of file";
    return false;
  }
  if (parsed_clauses != nclauses) {
    error = "header declares " + std::to_string(nclauses) + " clauses but file has " +
            std::to_string(parsed_clauses);
    return false;
  }
  return true;
}

bool writeDimacs(const std::string& path, const Formula& formula,
                 const std::vector<std::string>& comments, std::string& error) {
  std::ofstream output(path);
  if (!output) {
    error = "cannot open file for writing: " + path;
    return false;
  }

  for (const std::string& comment : comments) {
    output << "c " << comment << '\n';
  }
  output << "p cnf " << formula.nvars << ' ' << formula.clauses.size() << '\n';
  for (const auto& clause : formula.clauses) {
    for (Lit p : clause) {
      int variable = var(p) + 1;
      output << (sign(p) ? -variable : variable) << ' ';
    }
    output << "0\n";
  }
  if (!output) {
    error = "failed while writing: " + path;
    return false;
  }
  return true;
}

}  // namespace sat
