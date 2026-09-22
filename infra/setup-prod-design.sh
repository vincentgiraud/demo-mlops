#!/bin/bash
# setup-mlops-envs.sh
# Complete provisioning script for the "Plan and prepare an MLOps solution" lab.
# Creates a dev workspace, a prod workspace, and a shared Azure ML registry,
# each in their own resource group with isolated data assets.

# ---------------------------------------------------------------------------
# Shared variables
# ---------------------------------------------------------------------------
guid=$(cat /proc/sys/kernel/random/uuid)
suffix=${guid//[-]/}
suffix=${suffix:0:18}

RESOURCE_PROVIDER="Microsoft.MachineLearningServices"
REGIONS=("eastus" "westus" "centralus" "northeurope")
RANDOM_REGION=${REGIONS[$RANDOM % ${#REGIONS[@]}]}

# Dev environment
DEV_RESOURCE_GROUP="rg-demo-dev-${suffix}"
DEV_WORKSPACE_NAME="mlw-demo-dev-${suffix}"

# Prod environment
PROD_RESOURCE_GROUP="rg-demo-prod-${suffix}"
PROD_WORKSPACE_NAME="mlw-demo-prod-${suffix}"

# Shared registry
REGISTRY_RESOURCE_GROUP="rg-demo-reg-${suffix}"
REGISTRY_NAME="mlr-demo-shrd-${suffix}"

# Compute
COMPUTE_INSTANCE="ci${suffix}"
COMPUTE_CLUSTER="aml-cluster"

# ---------------------------------------------------------------------------
# Register the Azure Machine Learning resource provider
# ---------------------------------------------------------------------------
echo "Registering the Machine Learning resource provider..."
az provider register --namespace $RESOURCE_PROVIDER

# ---------------------------------------------------------------------------
# Dev environment
# ---------------------------------------------------------------------------
echo "Creating dev resource group: $DEV_RESOURCE_GROUP"
az group create --name $DEV_RESOURCE_GROUP --location $RANDOM_REGION

echo "Creating dev workspace: $DEV_WORKSPACE_NAME"
az ml workspace create --name $DEV_WORKSPACE_NAME --resource-group $DEV_RESOURCE_GROUP

az configure --defaults group=$DEV_RESOURCE_GROUP workspace=$DEV_WORKSPACE_NAME

echo "Creating compute instance for dev workspace..."
az ml compute create --name $COMPUTE_INSTANCE --size STANDARD_E2DS_V5 --type ComputeInstance

echo "Creating compute cluster for dev workspace..."
az ml compute create --name $COMPUTE_CLUSTER --size STANDARD_E2DS_V5 --max-instances 2 --type AmlCompute

echo "Creating dev data assets..."
az ml data create --type mltable --name "diabetes-training" --path ../data/diabetes-data
az ml data create --type uri_file --name "diabetes-data" --path ../data/diabetes-data/diabetes.csv
az ml data create --type uri_folder --name "diabetes-dev-folder" --path ../data/diabetes-data

# ---------------------------------------------------------------------------
# Prod environment
# ---------------------------------------------------------------------------
echo "Creating prod resource group: $PROD_RESOURCE_GROUP"
az group create --name $PROD_RESOURCE_GROUP --location $RANDOM_REGION

echo "Creating prod workspace: $PROD_WORKSPACE_NAME"
az ml workspace create --name $PROD_WORKSPACE_NAME --resource-group $PROD_RESOURCE_GROUP

az configure --defaults group=$PROD_RESOURCE_GROUP workspace=$PROD_WORKSPACE_NAME

echo "Creating prod data asset..."
az ml data create \
    --type uri_folder \
    --name "diabetes-prod-folder" \
    --path ../production/data

# ---------------------------------------------------------------------------
# Shared registry
# ---------------------------------------------------------------------------
echo "Creating registry resource group: $REGISTRY_RESOURCE_GROUP"
az group create --name $REGISTRY_RESOURCE_GROUP --location $RANDOM_REGION

echo "Rendering registry.yml with dynamic values..."
sed \
    -e "s|REGISTRY_NAME_PLACEHOLDER|$REGISTRY_NAME|g" \
    -e "s|PRIMARY_REGION_PLACEHOLDER|$RANDOM_REGION|g" \
    registry.yml > registry.generated.yml

echo "Creating shared Azure Machine Learning registry: $REGISTRY_NAME"
az ml registry create \
    --file registry.generated.yml \
    --resource-group $REGISTRY_RESOURCE_GROUP
    

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
echo ""
echo "Provisioning complete."
echo "  Dev workspace:   $DEV_WORKSPACE_NAME  ($DEV_RESOURCE_GROUP)"
echo "  Prod workspace:  $PROD_WORKSPACE_NAME  ($PROD_RESOURCE_GROUP)"
echo "  Shared registry: $REGISTRY_NAME  ($REGISTRY_RESOURCE_GROUP)"
