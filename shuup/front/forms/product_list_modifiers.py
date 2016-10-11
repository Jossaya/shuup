# -*- coding: utf-8 -*-
# This file is part of Shuup.
#
# Copyright (c) 2012-2016, Shoop Commerce Ltd. All rights reserved.
#
# This source code is licensed under the AGPLv3 license found in the
# LICENSE file in the root directory of this source tree.
from collections import defaultdict
from itertools import chain

import six
from django import forms
from django.db.models import Q
from django.template.loader import render_to_string
from django.utils.safestring import mark_safe
from django.utils.text import capfirst, slugify
from django.utils.translation import ugettext_lazy as _
from django.utils.translation import get_language

from shuup.core.models import (
    Category, Manufacturer, ProductVariationVariable, ShopProduct
)
from shuup.front.utils.sorts_and_filters import ProductListFormModifier


class FilterWidget(forms.SelectMultiple):
    def render(self, name, value, attrs=None, choices=()):
        if value is None:
            value = []
        choices_to_render = []
        for option_value, option_label in chain(self.choices, choices):
            choices_to_render.append((option_value, option_label))
        return mark_safe(
            render_to_string("shuup/front/product/filter_choice.jinja", {
                "name": name, "values": value, "choices": choices_to_render})
        )


class SimpleProductListModifier(ProductListFormModifier):
    is_active_key = ""
    is_active_label = ""
    ordering_key = ""
    ordering_label = ""

    def should_use(self, configuration):
        if not configuration:
            return
        return bool(configuration.get(self.is_active_key))

    def get_ordering(self, configuration):
        if not configuration:
            return 1
        return configuration.get(self.ordering_key, 1)

    def get_admin_fields(self):
        return [
            (self.is_active_key, forms.BooleanField(label=self.is_active_label, required=False)),
            (self.ordering_key, forms.IntegerField(label=self.ordering_label, initial=1))
        ]


class SortProductListByName(SimpleProductListModifier):
    is_active_key = "sort_products_by_name"
    is_active_label = _("Sort products by name")
    ordering_key = "sort_products_by_name_ordering"
    ordering_label = _("Ordering for sort by name")

    def get_fields(self, request, category=None):
        return [("sort", forms.CharField(required=False, widget=forms.Select(), label=_('Sort')))]

    def get_choices_for_fields(self):
        return [
            ("sort", [
                ("name_a", _("Name - A-Z")),
                ("name_d", _("Name - Z-A")),
            ]),
        ]

    def sort_products(self, request, products, sort):
        def _get_product_name_lowered_stripped(product):
            return product.name.lower().strip()

        if not sort:
            sort = ""

        key = (sort[:-2] if sort.endswith(('_a', '_d')) else sort)
        if key == "name":
            sorter = _get_product_name_lowered_stripped
            reverse = bool(sort.endswith('_d'))
            products = sorted(products, key=sorter, reverse=reverse)
        return products


class SortProductListByPrice(SimpleProductListModifier):
    is_active_key = "sort_products_by_price"
    is_active_label = _("Sort products by price")
    ordering_key = "sort_products_by_price_ordering"
    ordering_label = _("Ordering for sort by price")

    def get_fields(self, request, category=None):
        return [("sort", forms.CharField(required=False, widget=forms.Select(), label=_('Sort')))]

    def get_choices_for_fields(self):
        return [
            ("sort", [
                ("price_a", _("Price - Low to High")),
                ("price_d", _("Price - High to Low")),
            ]),
        ]

    def sort_products(self, request, products, sort):
        def _get_product_price_getter_for_request(request):
            def _get_product_price(product):
                return product.get_price(request)
            return _get_product_price

        if not sort:
            sort = ""

        key = (sort[:-2] if sort.endswith(('_a', '_d')) else sort)
        if key == "price":
            reverse = bool(sort.endswith('_d'))
            sorter = _get_product_price_getter_for_request(request)
            return sorted(products, key=sorter, reverse=reverse)
        return products


class SortProductListByCreatedDate(SimpleProductListModifier):
    is_active_key = "sort_products_by_date_created"
    is_active_label = _("Sort products by date created")
    ordering_key = "sort_products_by_date_created_ordering"
    ordering_label = _("Ordering for sort by date created")

    def get_fields(self, request, category=None):
        return [("sort", forms.CharField(required=False, widget=forms.Select(), label=_('Sort')))]

    def get_choices_for_fields(self):
        return [
            ("sort", [
                ("created_date_d", _("Date created")),
            ]),
        ]

    def sort_products(self, request, products, sort):
        def _get_product_created_on_datetime(product):
            return product.created_on

        if not sort:
            sort = ""

        key = (sort[:-2] if sort.endswith(('_a', '_d')) else sort)
        if key == "created_date":
            sorter = _get_product_created_on_datetime
            reverse = bool(sort.endswith('_d'))
            products = sorted(products, key=sorter, reverse=reverse)
        return products


class ManufacturerProductListFilter(SimpleProductListModifier):
    is_active_key = "filter_products_by_manufacturer"
    is_active_label = _("Filter products by manufacturer")
    ordering_key = "filter_products_by_manufacturer_ordering"
    ordering_label = _("Ordering for filter by manufacturer")

    def get_fields(self, request, category=None):
        if not Manufacturer.objects.exists():
            return
        if category:
            manufacturer_ids = set(
                ShopProduct.objects.filter(
                    categories__in=[category]).values_list("product__manufacturer__pk", flat=True).distinct()
            )
            if manufacturer_ids == set([None]):
                return
            queryset = Manufacturer.objects.filter(pk__in=manufacturer_ids)
        else:
            queryset = Manufacturer.objects.all()
        return [
            (
                "manufacturers",
                forms.ModelMultipleChoiceField(
                    queryset=queryset, required=False, label=_('Manufacturers'), widget=FilterWidget())
            ),
        ]

    def get_filters(self, request, data):
        manufacturers = data.get("manufacturers")
        if manufacturers:
            return Q(manufacturer__in=manufacturers)


class CategoryProductListFilter(SimpleProductListModifier):
    is_active_key = "filter_products_by_category"
    is_active_label = _("Filter products by category")
    ordering_key = "filter_products_by_category_ordering"
    ordering_label = _("Ordering for filter by category")

    def get_fields(self, request, category=None):
        if not Category.objects.exists():
            return

        language = get_language()
        base_queryset = Category.objects.all_visible(request.customer, request.shop, language=language)
        if category:
            queryset = base_queryset.filter(shop_products__categories=category).exclude(pk=category.pk).distinct()
        else:
            # Show only first level when there is no category selected
            queryset = base_queryset.filter(parent=None)
        return [
            (
                "categories",
                forms.ModelMultipleChoiceField(
                    queryset=queryset, required=False, label=_('Categories'), widget=FilterWidget())
            ),
        ]

    def get_filters(self, request, data):
        categories = data.get("categories")
        if categories:
            return Q(shop_products__categories__in=list(categories))


class LimitProductListPageSize(SimpleProductListModifier):
    is_active_key = "limit_product_list_page_size"
    is_active_label = _("Limit page size")
    ordering_key = "limit_product_list_page_size_ordering"
    ordering_label = _("Ordering for limit page size")

    def get_fields(self, request, category=None):
        return [("limit", forms.IntegerField(required=False, widget=forms.Select(), label=_("Products per page")))]

    def get_choices_for_fields(self):
        return [
            ("limit", [(12, 12), (24, 24), (36, 36), (48, 48)]),
        ]


class ProductVariationFilter(SimpleProductListModifier):
    is_active_key = "filter_products_by_variation_value"
    is_active_label = _("Filter products by variation")
    ordering_key = "filter_products_by_variation_value_ordering"
    ordering_label = _("Ordering for filter by variation")

    def get_fields(self, request, category=None):
        if not category:
            return

        variation_values = defaultdict(set)
        for variation in ProductVariationVariable.objects.filter(product__shop_products__categories=category):
            for value in variation.values.all():
                variation_values[slugify(variation.name)].add(value.value)

        fields = []
        for variation_key, variation_values in six.iteritems(variation_values):
            choices = [(value.lower(), value) for value in variation_values]

            fields.append((
                "variation_%s" % variation_key,
                forms.MultipleChoiceField(
                    choices=choices, required=False, label=capfirst(variation_key), widget=FilterWidget())
            ))
        return fields

    def get_queryset(self, queryset, data):
        if not any([key for key in data.keys() if key.startswith("variation")]):
            return

        for key, values in six.iteritems(data):
            if key.startswith("variation"):
                variation_query = Q()
                for value in list(values):
                    variation_query |= Q(variation_variables__values__translations__value__iexact=value)
                queryset = queryset.filter(variation_query)
        return queryset