echo.
echo [5] Graph visualization - package A
py -3.10 src/main.py --package A --repository test_repository/test_graph.json --mode file --output graph_A.png

echo.
echo [5] Graph visualization - package B
py -3.10 src/main.py --package B --repository test_repository/test_graph.json --mode file --output graph_B.png

echo.
echo [5] Graph visualization - package E
py -3.10 src/main.py --package E --repository test_repository/test_graph.json --mode file --output graph_E.png

echo.
echo ==========================================
echo   All tests completed
echo ==========================================
pause