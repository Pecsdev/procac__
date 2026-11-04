from dateutil.relativedelta import relativedelta


SUBSCRIPTION_DURATIONS = {
    'starter': relativedelta(days=1),
    'standard': relativedelta(weeks=1),
    'premium': relativedelta(months=1),
    'enterprise': relativedelta(months=1),
    'ultimate_enterprise': relativedelta(months=2),
}


def calculate_subscription_expiry(start_date, duration):
    if isinstance(duration, str):
        try:
            duration = SUBSCRIPTION_DURATIONS[duration]
        except KeyError as error:
            raise ValueError(f'Unsupported subscription tier: {duration}') from error
    if not isinstance(duration, relativedelta):
        raise TypeError('duration must be a subscription tier or relativedelta.')
    return start_date + duration