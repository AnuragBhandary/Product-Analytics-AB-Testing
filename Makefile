.PHONY: install criteo-data criteo dbt export simulate dashboard-data dashboard dashboard-dev test lint check all

GCP_PROJECT ?= ab-analytics-511119
export GCP_PROJECT
# Keep the laptop usable: BLAS/sklearn/DuckDB stay on 4 threads, heavy steps run at low priority.
export OMP_NUM_THREADS ?= 4
NODE_PATH_PREFIX := $(HOME)/.local/node/bin

install:            ## Python deps incl. dbt-bigquery; dashboard npm deps
	uv sync --extra bigquery
	cd dashboard && PATH=$(NODE_PATH_PREFIX):$$PATH npm ci

criteo-data:        ## download Criteo uplift v2.1 (311 MB) -> data/criteo.parquet
	uv run ablab criteo-data

criteo:             ## experiment readout on 13,979,592 users (~50 s, 4 threads)
	nice -n 10 uv run ablab criteo

dbt:                ## build + test the GA4 models in BigQuery (needs gcloud ADC login)
	uv run dbt build --project-dir dbt --profiles-dir dbt

export:             ## BigQuery marts -> data/ga4/*.parquet
	uv run ablab export --project $(GCP_PROJECT)

simulate:           ## A/A, power, peeking, SRM simulations on GA4 users (~90 s)
	nice -n 10 uv run ablab simulate

dashboard-data:     ## results + marts -> dashboard DuckDB + Power BI CSVs
	uv run ablab dashboard-data

dashboard:          ## static Evidence site -> dashboard/build
	cd dashboard && PATH=$(NODE_PATH_PREFIX):$$PATH npm run sources && PATH=$(NODE_PATH_PREFIX):$$PATH npm run build

all: criteo dbt export simulate dashboard-data dashboard

test:
	uv run pytest --cov --cov-report=term

lint:
	uv run ruff check .
	uv run ruff format --check .
	uv run mypy
	uv run sqlfluff lint dbt/models dbt/tests

check: lint test
