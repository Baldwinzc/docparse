"""夹具 GT 字段名 → TextIn 报关单专用 API 字段名。"""

GT_TO_TEXTIN: dict[str, str] = {
    "预录入编号": "pre_entry_number",
    "海关编号": "customs_number",
    "境内发货人": "domestic_consignor",
    "出口日期": "export_date",
    "境外收货人": "overseas_consignee",
    "申报日期": "declaration_date",
    "生产销售单位": "production_and_sales_company",
    "运输方式": "transportation_mode",
    "合同协议号": "contract_agreement_number",
    "监管方式": "supervision_way",
    "贸易国（地区）": "trading_country",
    "征免性质": "taxation",
    "指运港": "port_of_destination",
    "成交方式": "terms_of_delivery",
    "件数": "number_of_packages",
    "毛重（千克）": "gross_weight",
    "净重（千克）": "net_weight",
    "包装种类": "packing_type",
}
