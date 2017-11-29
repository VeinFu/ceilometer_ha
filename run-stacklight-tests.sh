#!/bin/bash -x
set -e
export OVERTEST_URL=stacklight://localhost:8086/ceilometer
./tools/pretty_tox.sh $*
