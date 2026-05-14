# Publish a Docker image (manual).
 #
 # Requirements:
 # - Docker installed with buildx support (e.g. Docker Desktop).
 # - Authenticated to the target registry (e.g. run: docker login).
 # - Run from the `tools/` directory (this script uses build context `.` and Dockerfile `../Server/Dockerfile`).
 #
 # Usage:
 #   ./docker_publish.sh <image> <version>
 #   IMAGE=<image> ./docker_publish.sh <version>
 #
 # Examples:
 #   ./docker_publish.sh msanatan/mcp-for-unity-server 9.6.8.1
 #   IMAGE=msanatan/mcp-for-unity-server ./docker_publish.sh v9.6.8.1
 #
 # Tags pushed:
 # - vX.Y.Z.N
 # - vX.Y
 # - vX
 set -euo pipefail
 
 if [[ "${1:-}" == "" || "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
   echo "Usage: $(basename "$0") <image> <version>" >&2
   echo "       $(basename "$0") <version>        # if IMAGE env var is set" >&2
   echo "Example: $(basename "$0") youruser/mcp-for-unity-server 1.2.3" >&2
   exit 2
 fi
 
 if [[ "${2:-}" != "" ]]; then
   IMAGE="$1"
   VERSION_RAW="$2"
 else
   if [[ "${IMAGE:-}" == "" ]]; then
     echo "Error: IMAGE env var is required when calling with a single arg." >&2
     echo "Usage: $(basename "$0") <image> <version>" >&2
     exit 2
   fi
   VERSION_RAW="$1"
 fi
 
 VERSION="${VERSION_RAW#v}"
 
IFS='.' read -r MAJOR MINOR_PART REST <<< "$VERSION"
MINOR="${MAJOR}.${MINOR_PART}"
 
 docker buildx build \
   --platform linux/amd64 \
   -f ../Server/Dockerfile \
   -t "$IMAGE:v$VERSION" \
   -t "$IMAGE:v$MINOR" \
   -t "$IMAGE:v$MAJOR" \
   --push \
   .
