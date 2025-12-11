#!/bin/bash
# Test runner script for Meido bot

echo "Running Meido Bot Tests..."
echo "=========================="
echo ""

# Check if pytest is installed
if ! command -v pytest &> /dev/null; then
    echo "pytest not found. Installing test dependencies..."
    pip install -r requirements.txt
fi

# Run tests with coverage
echo "Running all tests..."
pytest tests/ -v --tb=short

echo ""
echo "=========================="
echo "Tests completed!"
