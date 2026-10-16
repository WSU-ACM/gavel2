from gavel.models import ma

from gavel.models import Annotator


class AnnotatorSchema(ma.ModelSchema):
    class Meta:
        model = Annotator
        exclude = ('secret', 'external_id', 'managed_source')
