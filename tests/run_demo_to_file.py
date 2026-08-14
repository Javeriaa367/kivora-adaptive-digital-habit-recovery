import sys
from pathlib import Path

# Ensure repo root is on sys.path when running this script directly
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tests.simulate_recovery_engine_demo import (
    scenario_1, scenario_2, scenario_3, scenario_4, scenario_5, scenario_6,
)

OUT = Path(__file__).with_name("simulate_outputs.txt")

def main():
    # Run scenarios and capture stdout into a file
    with OUT.open("w", encoding="utf-8") as f:
        # Monkeypatch print to write to file for imported module functions
        import builtins
        real_print = builtins.print

        def file_print(*args, **kwargs):
            real_print(*args, **kwargs)
            sep = kwargs.get('sep', ' ')
            end = kwargs.get('end', '\n')
            f.write(sep.join(str(a) for a in args) + end)

        builtins.print = file_print
        try:
            scenario_1()
            scenario_2()
            scenario_3()
            scenario_4()
            # scenario_5 and scenario_6 interact with the DB and need the Flask app context
            from app import app as flask_app
            with flask_app.app_context():
                scenario_5()
                scenario_6()
        finally:
            builtins.print = real_print

if __name__ == '__main__':
    main()
