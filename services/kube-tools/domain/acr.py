from datetime import datetime
from typing import Dict

from framework.logger import get_logger
from framework.serialization import Serializable

logger = get_logger(__name__)


class AcrImage(Serializable):
    def __init__(
        self,
        id: str,
        tag: str,
        image_size: int,
        created_date: datetime
    ):
        self.id = id
        self.tag = tag
        self.image_size = image_size
        self.created_date = created_date

    @staticmethod
    def from_dict(
        data: Dict
    ):
        return AcrImage(
            id=data.get('id'),
            tag=data.get('tag'),
            image_size=data.get('image_size'),
            created_date=data.get('created_date'))

    @staticmethod
    def from_manifest(
        data: Dict
    ):
        tags = data.get('tags', [])

        if not any(tags):
            tag = 'no-tag'
        else:
            tag = tags[0]

        return AcrImage(
            id=data.get('digest'),
            tag=tag,
            image_size=data.get('imageSize'),
            created_date=data.get('createdTime'))


# class Image:
#     def __init__(
#         self,
#         data: Dict
#     ):
#         self.repository = data.get('repository')
#         self.manifest_id = data.get('id')
#         self.tag = data.get('tags')
#         self.days_old = data.get('days_old')
#         self.size = data.get('size')
#         self.full_name = f'{self.repository}:{self.tag}'
#         self.image_name = self.repository.replace('azureks.azurecr.io/', '')


# class ManifestInfo(Serializable):
#     @property
#     def full_name(self):
#         return self.get_image_info().full_name

#     @property
#     def image_name(self):
#         return self.get_image_info().image_name

#     def __init__(self, manifest, repository_name):
#         now = datetime.utcnow().replace(tzinfo=None)

#         manifest_updated = manifest.get('lastUpdateTime')
#         self.updated = parser.parse(manifest_updated).replace(
#             tzinfo=None)

#         self.id = manifest.get('digest')
#         self.days_old = (now - self.updated).days
#         self.repository = f'azureks.azurecr.io/{repository_name}'
#         self.size = manifest.get('imageSize')
#         self.created = manifest.get('createdTime')
#         self.updated = manifest.get('lastUpdateTime')
#         self.tags = manifest.get('tags')[0]

#     def get_image_info(self):
#         return Image(
#             data=self.to_dict())


# class RepositoryInfo:
#     def __init__(
#         self,
#         repository_name: str,
#         manifests: List[ManifestInfo]
#     ):
#         self.repository_name = repository_name
#         self.manifests = manifests or []

#     def get_purge_images(
#         self,
#         k8s_images,
#         k8s_image_counts,
#         threshold_days,
#         keep_top_image_count
#     ) -> List[ManifestInfo]:

#         # Get current repo image (manifest) count for repository
#         image_count = first(k8s_image_counts, lambda x: x.get(
#             'repository') == self.repository_name) or dict()
#         logger.info(f'Images in repo: {self.repository_name}: {image_count}')

#         image_count = image_count.get('count', 0)

#         k8s_image_names = [x.get('image') for x in k8s_images]

#         purge = []
#         for manifest in self.manifests:
#             image_info = manifest.get_image_info()
#             logger.info(f'Manifest: {manifest.id}')

#             # Get indicators for purge eligiblity
#             exceeds_age = int(image_info.days_old) >= int(threshold_days)
#             live_on_pod = image_info.full_name in k8s_image_names
#             exceeds_top = len(self.manifests) > keep_top_image_count

#             if exceeds_age and exceeds_top and not live_on_pod:
#                 logger.info(f'Manifest: {manifest.id}: Adding to purge queue')
#                 purge.append(manifest)

#         return purge
