IMAGE_NAME ?= gtc-mcp
IMAGE_TAG ?= latest
ZOT_REGISTRY ?= zot.local:5000
CONTAINER_RUNTIME ?= docker
PLATFORMS ?= linux/amd64,linux/arm64
BUILDX_BUILDER ?= gtc-mcp-builder

LOCAL_IMAGE := $(IMAGE_NAME):$(IMAGE_TAG)
REGISTRY_IMAGE := $(ZOT_REGISTRY)/$(IMAGE_NAME):$(IMAGE_TAG)

.PHONY: help docker-build docker-tag docker-push docker-publish docker-run buildx-create docker-buildx docker-publishx

help:
	@printf '%s\n' \
		'make docker-build    Build the local container image' \
		'make docker-buildx   Build a multi-arch image with buildx' \
		'make docker-tag      Tag the local image for the Zot registry' \
		'make docker-push     Push the tagged image to the Zot registry' \
		'make docker-publish  Build, tag, and push the image' \
		'make docker-publishx Build and push a multi-arch image to the Zot registry' \
		'make docker-run      Run the image locally in streamable HTTP mode' \
		'' \
		'Variables:' \
		'  IMAGE_NAME=gtc-mcp' \
		'  IMAGE_TAG=latest' \
		'  ZOT_REGISTRY=zot.local:5000' \
		'  CONTAINER_RUNTIME=docker' \
		'  PLATFORMS=linux/amd64,linux/arm64' \
		'  BUILDX_BUILDER=gtc-mcp-builder'

docker-build:
	$(CONTAINER_RUNTIME) build -t $(LOCAL_IMAGE) .

docker-tag:
	$(CONTAINER_RUNTIME) tag $(LOCAL_IMAGE) $(REGISTRY_IMAGE)

docker-push:
	$(CONTAINER_RUNTIME) push $(REGISTRY_IMAGE)

docker-publish: docker-build docker-tag docker-push

docker-run:
	$(CONTAINER_RUNTIME) run --rm -p 8000:8000 -v $(CURDIR)/.cache:/data $(LOCAL_IMAGE)

buildx-create:
	-$(CONTAINER_RUNTIME) buildx inspect $(BUILDX_BUILDER) >/dev/null 2>&1 || $(CONTAINER_RUNTIME) buildx create --name $(BUILDX_BUILDER) --use
	$(CONTAINER_RUNTIME) buildx use $(BUILDX_BUILDER)
	$(CONTAINER_RUNTIME) buildx inspect --bootstrap

docker-buildx: buildx-create
	$(CONTAINER_RUNTIME) buildx build --platform $(PLATFORMS) -t $(REGISTRY_IMAGE) .

docker-publishx: buildx-create
	$(CONTAINER_RUNTIME) buildx build --platform $(PLATFORMS) -t $(REGISTRY_IMAGE) --push .
