"""
Serializers for the ES's search result object.

.. note::
   Some fields are re-named to make their meaning more clear.
   They should be renamed in the ES index too.
"""

import itertools
import re
from functools import namedtuple
from operator import attrgetter
from urllib.parse import urlparse

from django.shortcuts import get_object_or_404
from rest_framework import serializers

from readthedocs.core.resolver import resolve
from readthedocs.projects.constants import MKDOCS, SPHINX_HTMLDIR
from readthedocs.projects.models import Project


# Structure used for storing cached data of a project mostly.
ProjectData = namedtuple('ProjectData', ['docs_url', 'version_doctype'])


def get_raw_field(obj, field, default=None):
    """Get the ``raw`` version of this field or fallback to the original field."""
    return (
        getattr(obj, f'{field}.raw', default)
        or getattr(obj, field, default)
    )


class ProjectHighlightSerializer(serializers.Serializer):

    name = serializers.SerializerMethodField()
    slug = serializers.SerializerMethodField()
    description = serializers.SerializerMethodField()

    def get_name(self, obj):
        return list(get_raw_field(obj, 'name', []))

    def get_slug(self, obj):
        return list(get_raw_field(obj, 'slug', []))

    def get_description(self, obj):
        return list(get_raw_field(obj, 'description', []))


class ProjectSearchSerializer(serializers.Serializer):

    type = serializers.CharField(default='project', source=None, read_only=True)
    name = serializers.CharField()
    slug = serializers.CharField()
    link = serializers.CharField(source='url')
    highlights = ProjectHighlightSerializer(source='meta.highlight', default=dict)


class PageHighlightSerializer(serializers.Serializer):

    title = serializers.SerializerMethodField()

    def get_title(self, obj):
        return list(get_raw_field(obj, 'title', []))


class PageSearchSerializer(serializers.Serializer):

    """
    Page serializer.

    If ``projects_data`` is passed into the context, the serializer
    will try to use that to generate the link before querying the database.
    It's a dictionary mapping the project slug to a ProjectData object.
    """

    type = serializers.CharField(default='page', source=None, read_only=True)
    project = serializers.CharField()
    version = serializers.CharField()
    title = serializers.CharField()
    path = serializers.SerializerMethodField()
    domain = serializers.SerializerMethodField()
    highlights = PageHighlightSerializer(source='meta.highlight', default=dict)
    blocks = serializers.SerializerMethodField()

    def get_domain(self, obj):
        full_path = self._get_full_path(obj)
        if full_path:
            parsed = urlparse(full_path)
            return f'{parsed.scheme}://{parsed.netloc}'
        return None

    def get_path(self, obj):
        full_path = self._get_full_path(obj)
        if full_path:
            parsed = urlparse(full_path)
            return parsed.path
        return None

    def _get_full_path(self, obj):
        """
        Get the page link.

        Try to get the link from the ``project_data`` context,
        and fallback to get it from the database.
        If the result is fetched from the database,
        it's cached into ``project_data``.
        """
        # First try to build the URL from the context.
        project_data = self.context.get('projects_data', {}).get(obj.project)
        if project_data:
            docs_url, doctype = project_data
            path = obj.full_path

            # Generate an appropriate link for the doctypes that use htmldir,
            # and always end it with / so it goes directly to proxito.
            if doctype in {SPHINX_HTMLDIR, MKDOCS}:
                path = re.sub('(^|/)index.html$', '/', path)

            return docs_url.rstrip('/') + '/' + path.lstrip('/')

        # Fallback to build the URL querying the db.
        project = Project.objects.filter(slug=obj.project).first()
        if project:
            docs_url = project.get_docs_url(version_slug=obj.version)
            # cache the project URL
            projects_data = self.context.setdefault('projects_data', {})
            projects_data[obj.project] = ProjectData(docs_url, '')
            return docs_url + obj.full_path

        return None

    def get_blocks(self, obj):
        """Combine and sort inner results (domains and sections)."""
        serializers = {
            'domain': DomainSearchSerializer,
            'section': SectionSearchSerializer,
        }

        inner_hits = obj.meta.inner_hits
        sections = inner_hits.sections or []
        domains = inner_hits.domains or []

        # Make them identifiable before merging them
        for s in sections:
            s.type = 'section'
        for d in domains:
            d.type = 'domain'

        sorted_results = sorted(
            itertools.chain(sections, domains),
            key=attrgetter('meta.score'),
            reverse=True,
        )
        sorted_results = [
            serializers[hit.type](hit).data
            for hit in sorted_results
        ]
        return sorted_results


class DomainHighlightSerializer(serializers.Serializer):

    name = serializers.SerializerMethodField()
    content = serializers.SerializerMethodField()

    def get_name(self, obj):
        return list(get_raw_field(obj, 'domains.name', []))

    def get_content(self, obj):
        return list(get_raw_field(obj, 'domains.docstrings', []))


class DomainSearchSerializer(serializers.Serializer):

    type = serializers.CharField(default='domain', source=None, read_only=True)
    role = serializers.CharField(source='role_name')
    name = serializers.CharField()
    id = serializers.CharField(source='anchor')
    content = serializers.CharField(source='docstrings')
    highlights = DomainHighlightSerializer(source='meta.highlight', default=dict)


class SectionHighlightSerializer(serializers.Serializer):

    title = serializers.SerializerMethodField()
    content = serializers.SerializerMethodField()

    def get_title(self, obj):
        return list(get_raw_field(obj, 'sections.title', []))

    def get_content(self, obj):
        return list(get_raw_field(obj, 'sections.content', []))


class SectionSearchSerializer(serializers.Serializer):

    type = serializers.CharField(default='section', source=None, read_only=True)
    id = serializers.CharField()
    title = serializers.CharField()
    content = serializers.CharField()
    highlights = SectionHighlightSerializer(source='meta.highlight', default=dict)
