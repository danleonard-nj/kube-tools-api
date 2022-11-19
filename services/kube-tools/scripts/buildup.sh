#!/bin/sh

certname="ca.crt"
configname="configs/kube-tools/kube-tools/config.json"
credentialname="configs/kube-tools/kube-tools/credentials.json"
tokenname="configs/kube-tools/kube-tools/token.json"
mfpname="configs/kube-tools/kube-tools/myfitnesspal.json"


az storage blob download --account-name stazureks --container-name build-resources --name $certname --file ca.crt
az storage blob download --account-name stazureks --container-name build-resources --name $configname --file config.json
az storage blob download --account-name stazureks --container-name build-resources --name $credentialname --file credentials.json
az storage blob download --account-name stazureks --container-name build-resources --name $tokenname --file token.json
az storage blob download --account-name stazureks --container-name build-resources --name $mfpname --file myfitnesspal.json


cp ca.crt services/kube-tools/clients/certificates
cp config.json services/kube-tools
cp credentials.json services/kube-tools
cp token.json services/kube-tools
cp myfitnesspal.json services/kube-tools