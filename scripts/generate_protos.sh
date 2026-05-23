#!/bin/bash
# RUVAMCO — Generate Envoy xDS Protobuf Stubs
#
# Downloads the Envoy API proto definitions and generates Python gRPC stubs
# for the control plane's ADS (Aggregated Discovery Service) server.
#
# Prerequisites:
#   pip install grpcio-tools
#
# Usage:
#   ./scripts/generate_protos.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
OUTPUT_DIR="$PROJECT_ROOT/control_plane/generated"
PROTO_TMP="/tmp/envoy-protos"

echo "📦 Generating Envoy xDS protobuf stubs..."

# Clean previous output
rm -rf "$OUTPUT_DIR"
mkdir -p "$OUTPUT_DIR"

# Clone Envoy API protos (shallow clone for speed)
if [ -d "$PROTO_TMP" ]; then
    echo "🔄 Updating existing proto checkout..."
    cd "$PROTO_TMP" && git pull --depth=1 origin main
else
    echo "⬇️  Cloning Envoy API protos..."
    git clone --depth=1 https://github.com/envoyproxy/envoy.git "$PROTO_TMP"
fi

# Also need googleapis and validate protos (Envoy deps)
GOOGLEAPIS_TMP="/tmp/googleapis"
if [ ! -d "$GOOGLEAPIS_TMP" ]; then
    git clone --depth=1 https://github.com/googleapis/googleapis.git "$GOOGLEAPIS_TMP"
fi

VALIDATE_TMP="/tmp/protoc-gen-validate"
if [ ! -d "$VALIDATE_TMP" ]; then
    git clone --depth=1 https://github.com/bufbuild/protoc-gen-validate.git "$VALIDATE_TMP"
fi

CNCF_TMP="/tmp/xds-protos"
if [ ! -d "$CNCF_TMP" ]; then
    git clone --depth=1 https://github.com/cncf/xds.git "$CNCF_TMP"
fi

# Generate Python + gRPC stubs for ADS
echo "🔨 Compiling protos..."
python -m grpc_tools.protoc \
    -I"$PROTO_TMP/api" \
    -I"$GOOGLEAPIS_TMP" \
    -I"$VALIDATE_TMP" \
    -I"$CNCF_TMP" \
    --python_out="$OUTPUT_DIR" \
    --grpc_python_out="$OUTPUT_DIR" \
    "$PROTO_TMP"/api/envoy/service/discovery/v3/*.proto \
    "$PROTO_TMP"/api/envoy/config/listener/v3/listener.proto \
    "$PROTO_TMP"/api/envoy/config/cluster/v3/cluster.proto \
    "$PROTO_TMP"/api/envoy/config/route/v3/route.proto \
    "$PROTO_TMP"/api/envoy/config/endpoint/v3/endpoint.proto

# Create __init__.py files for package imports
find "$OUTPUT_DIR" -type d -exec touch {}/__init__.py \;

echo "✅ Protobuf stubs generated in $OUTPUT_DIR"
echo "   Import with: from control_plane.generated import envoy_service_discovery_v3_pb2_grpc"
