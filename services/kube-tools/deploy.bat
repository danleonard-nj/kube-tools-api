docker build -t azureks.azurecr.io/kube-tools/kube-tools:2055 .
docker push azureks.azurecr.io/kube-tools/kube-tools:2055
kubectl rollout restart deployment kube-tools -n kube-tools