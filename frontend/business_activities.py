DIGITAL_SERVICE_TYPES = (
    'Commerce & Retail Services',
    'Communication Services',
    'Computing Services',
    'Construction Services',
    'Content Services',
    'Digital Public Infrastructure Services',
    'Education Services',
    'Environmental Services',
    'Financial Services',
    'Healthcare Services',
    'Human Resources Services',
    'Manufacturing Services',
    'Professional Services',
    'Smart Consumer Devices Services',
    'Transport & Logistics Services',
)

BUSINESS_ACTIVITY_MAP = {
    'Real Estate Activities': ('Real Estate Activities',),
    'Accommodation And Food Services Activities': (
        'Accommodation And Food Services Activities',
    ),
    'Activities Of Extraterritorial Organisation And Bodies': (
        'Activities Of Extraterritorial Organisation And Bodies',
    ),
    'Administrative And Support Services Activities': (
        'Administrative And Support Services Activities',
    ),
    'Agriculture Forestry & Fishing': ('Agriculture Forestry & Fishing',),
    'Art, Entertainment And Recreation': ('Art, Entertainment And Recreation',),
    'Construction': ('Construction',),
    **{
        f'Digital Services - {service_type}': (service_type,)
        for service_type in DIGITAL_SERVICE_TYPES
    },
    'Education': ('Education',),
    'Faith Based Association': ('Faith Based Association',),
    'Financial And Insurance Activities': ('Financial And Insurance Activities',),
    'Foundation Based Association': ('Foundation Based Association',),
    'Human Health': ('Human Health',),
    'Information And Communication': ('Information And Communication',),
    'Manufacturing': ('General Manufacturing & Processing',),
    'Mining And Quarrying': ('Mining And Quarrying',),
    'Power': ('Power',),
    'Professional/Scientific/Technical': ('Professional/Scientific/Technical',),
    'Public Administration': ('Public Administration',),
    'Repairs': ('Repairs',),
    'Social/Sporting Associations': ('Social/Sporting Associations',),
    'Transportation': ('Transportation',),
    'Water Supply': ('Water Supply',),
    'Wholesale and Retail Trade': ('Wholesale and Retail Trade',),
}

PRINCIPAL_ACTIVITY_CHOICES = tuple(
    (activity, activity)
    for activity in BUSINESS_ACTIVITY_MAP
)
SPECIFIC_ACTIVITY_CHOICES = tuple(dict.fromkeys(
    (specific, specific)
    for specific_options in BUSINESS_ACTIVITY_MAP.values()
    for specific in specific_options
))
