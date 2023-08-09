from .model import BertForTagging
from .model import BertCRFForTagging
# from .model import BertForRoleLabeling
from .model import BertDNNForRoleLabeling
# from .model import BertCRFForRoleLabeling

__all__ = [
    'BertDNNForRoleLabeling',
    'BertDNNForTagging',
    'BertForTagging',
    'BertCRFForTagging',
    'BertForRoleLabeling',
    'BertCRFForRoleLabeling'
]
