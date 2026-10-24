PY ?= ../.venv-agent/bin/python

.PHONY: demo conflict timing deploy

demo:       ## one clean file, end to end
	$(PY) run_desk.py clean_file

conflict:   ## the file where two agents disagree
	$(PY) run_desk.py conflict_file

timing:     ## same file, concurrent then sequential
	$(PY) run_desk.py conflict_file
	$(PY) run_desk.py conflict_file --sequential

deploy:
	./underwriting_mcp/deploy.sh
	./underwriting_agent/deploy.sh
