from typing import List
from framework.logger import get_logger
from datetime import datetime
from framework.serialization import Serializable
from dateutil import parser

logger = get_logger(__name__)


def first(items, func):
    for item in items:
        if func(item) is True:
            return item


class AcrServiceCacheKey:
    ManifestInfo = 'acr-service-manifest-info'
    K8sImages = 'acr-service-k8s-images'


class Image:
    def __init__(self, data):
        self.repository = data.get('repository')
        self.manifest_id = data.get('id')
        self.tag = data.get('tags')
        self.days_old = data.get('days_old')
        self.size = data.get('size')
        self.full_name = f'{self.repository}:{self.tag}'
        self.image_name = self.repository.replace('azureks.azurecr.io/', '')


class ManifestInfo(Serializable):
    @property
    def full_name(self):
        return self.get_image_info().full_name

    @property
    def image_name(self):
        return self.get_image_info().image_name

    def __init__(self, manifest, repository_name):
        now = datetime.utcnow().replace(tzinfo=None)

        manifest_updated = manifest.get('lastUpdateTime')
        self.updated = parser.parse(manifest_updated).replace(
            tzinfo=None)

        self.id = manifest.get('digest')
        self.days_old = (now - self.updated).days
        self.repository = f'azureks.azurecr.io/{repository_name}'
        self.size = manifest.get('imageSize')
        self.created = manifest.get('createdTime')
        self.updated = manifest.get('lastUpdateTime')
        self.tags = manifest.get('tags')[0]

    def get_image_info(self):
        return Image(
            data=self.to_dict())


class RepositoryInfo:
    def __init__(self, repository_name, manifests: List[ManifestInfo]):
        self.repository_name = repository_name
        self.manifests = manifests or []

    def get_purge_images(
        self,
        k8s_images,
        k8s_image_counts,
        threshold_days,
        keep_top_image_count
    ) -> List[ManifestInfo]:

        # Get current repo image (manifest) count for repository
        image_count = first(k8s_image_counts, lambda x: x.get(
            'repository') == self.repository_name) or dict()
        image_count = image_count.get('count', 0)

        logger.info(f'Repository: {self.repository_name}')
        logger.info(f'Image count: {len(self.manifests)}')

        k8s_image_names = [x.get('image') for x in k8s_images]

        purge = []
        for manifest in self.manifests:
            image_info = manifest.get_image_info()
            logger.info(f'Manifest: {manifest.id}')

            # Get indicators for purge eligiblity
            exceeds_age = int(image_info.days_old) >= int(threshold_days)
            live_on_pod = image_info.full_name in k8s_image_names
            exceeds_top = len(self.manifests) > keep_top_image_count

            if exceeds_age and exceeds_top and not live_on_pod:
                logger.info(f'Manifest: {manifest.id}: Adding to purge queue')
                purge.append(manifest)

        return purge
