docker build --build-arg ARTIFACT_FEED_TOKEN=%PAT% -t azureks.azurecr.io/kube-tools/kube-tools:3255 .
docker push azureks.azurecr.io/kube-tools/kube-tools:3255
kubectl rollout restart deployment kube-tools -n kube-tools