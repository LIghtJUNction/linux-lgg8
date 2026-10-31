/* SPDX-License-Identifier: GPL-2.0-only */
#include "test_fg_observer_shim.h"
#include "../../drivers/power/supply/qcom_fg_observer.c"

static unsigned int cases;
struct fixture { struct platform_device pdev; struct device parent; struct regmap map; };

static void setup(struct fixture *f, int count)
{
    memset(f, 0, sizeof(*f));
    f->pdev.dev.parent = &f->parent;
    f->parent.map = &f->map;
    f->pdev.dev.pmic.subtype = PM8150B_SUBTYPE;
    f->pdev.dev.node = (struct fwnode_handle) { .count = count,
        .bases = {0x4100, 0x4300, 0x4200, 0x4400} };
    f->map.bytes[0x4105] = 0x11;
    f->map.bytes[0x4305] = 0x0d;
    f->map.bytes[0x4205] = 0x13;
}
static void done(struct fixture *f)
{
    assert(f->map.writes == 0);
    free(f->pdev.dev.psy);
    free(f->pdev.dev.allocation);
    cases++;
}
static bool advertises(struct fixture *f, enum power_supply_property property)
{
    const struct power_supply_desc *d = f->pdev.dev.psy->desc;
    for (size_t i = 0; i < d->num_properties; i++)
        if (d->properties[i] == property) return true;
    return false;
}
static int get(struct fixture *f, enum power_supply_property property,
               union power_supply_propval *value)
{ return f->pdev.dev.psy->desc->get_property(f->pdev.dev.psy, property, value); }

static void presence(void)
{
    struct fixture f;
    union power_supply_propval value;
    setup(&f, 3);
    assert(fg_observer_probe(&f.pdev) == 0);
    assert(advertises(&f, POWER_SUPPLY_PROP_PRESENT));
    assert(f.map.read_count == 3);
    assert(f.map.reads[0] == 0x4105 && f.map.reads[1] == 0x4305 &&
           f.map.reads[2] == 0x4205);
    for (unsigned int status = 0; status < 256; status++) {
        f.map.read_count = 0;
        f.map.bytes[0x4210] = status;
        value.intval = 1234;
        assert(get(&f, POWER_SUPPLY_PROP_PRESENT, &value) == 0);
        assert(value.intval == !(status & 1));
        assert(f.map.read_count == 1 && f.map.reads[0] == 0x4210);
    }
    for (unsigned int i = 0; i < 2; i++) {
        value.intval = 1234;
        f.map.fail_reg = 0x4210;
        f.map.read_error = i ? -ETIMEDOUT : -EIO;
        assert(get(&f, POWER_SUPPLY_PROP_PRESENT, &value) == f.map.read_error);
        assert(value.intval == 1234);
    }
    f.map.read_error = 0;
    f.map.bytes[0x4210] = 3;
    assert(get(&f, POWER_SUPPLY_PROP_PRESENT, &value) == 0 && !value.intval);
    done(&f);
}
static void legacy_and_independent_nodes(void)
{
    for (unsigned int order = 0; order < 2; order++) {
        struct fixture old, modern;
        union power_supply_propval value = { .intval = 1234 };
        setup(&old, 2);
        setup(&modern, 3);
        if (order) {
            assert(fg_observer_probe(&modern.pdev) == 0);
            assert(fg_observer_probe(&old.pdev) == 0);
        } else {
            assert(fg_observer_probe(&old.pdev) == 0);
            assert(fg_observer_probe(&modern.pdev) == 0);
        }
        assert(!advertises(&old, POWER_SUPPLY_PROP_PRESENT));
        assert(advertises(&modern, POWER_SUPPLY_PROP_PRESENT));
        assert(old.map.read_count == 2 && old.map.reads[1] == 0x4305);
        old.map.read_count = 0;
        assert(get(&old, POWER_SUPPLY_PROP_PRESENT, &value) == -EOPNOTSUPP);
        assert(value.intval == 1234 && old.map.read_count == 0);
        modern.map.bytes[0x4210] = 2;
        assert(get(&modern, POWER_SUPPLY_PROP_PRESENT, &value) == 0 && value.intval == 1);
        assert(old.map.read_count == 0);
        done(&modern);
        /* Releasing the new node must not leave the legacy descriptor dangling. */
        assert(!advertises(&old, POWER_SUPPLY_PROP_PRESENT));
        done(&old);
    }
}
static void identities_and_faults(void)
{
    const unsigned int regs[] = {0x4105, 0x4305, 0x4205};
    for (int count = 2; count <= 3; count++) {
        for (unsigned int i = 0; i < (unsigned int)count; i++) {
            for (unsigned int failure = 0; failure < 3; failure++) {
                struct fixture f;
                setup(&f, count);
                if (!failure) f.map.bytes[regs[i]] ^= 1;
                else {
                    f.map.fail_reg = regs[i];
                    f.map.read_error = failure == 1 ? -EIO : -ETIMEDOUT;
                }
                assert(fg_observer_probe(&f.pdev) ==
                       (!failure ? -ENODEV : f.map.read_error));
                assert(!f.pdev.dev.psy && f.map.read_count == i + 1);
                done(&f);
            }
        }
    }
    for (int count = 0; count <= 4; count++) {
        struct fixture f;
        if (count == 2 || count == 3) continue;
        setup(&f, count);
        assert(fg_observer_probe(&f.pdev) == -EINVAL);
        assert(!f.map.read_count && !f.pdev.dev.psy);
        done(&f);
    }
    for (unsigned int mode = 0; mode < 6; mode++) {
        struct fixture f;
        int expected;
        setup(&f, 3);
        switch (mode) {
        case 0: f.pdev.dev.node.count_error = expected = -EIO; break;
        case 1: f.pdev.dev.node.read_error = expected = -EOVERFLOW; break;
        case 2: f.pdev.dev.pmic.subtype ^= 1; expected = -ENODEV; break;
        case 3: f.pdev.dev.pmic_error = expected = -EAGAIN; break;
        case 4: f.parent.map = NULL; expected = -ENODEV; break;
        default: f.pdev.dev.register_error = expected = -ENOMEM; break;
        }
        assert(fg_observer_probe(&f.pdev) == expected);
        assert(!f.pdev.dev.psy);
        assert(f.map.read_count == (mode == 5 ? 3U : 0U));
        done(&f);
    }
}
static void old_measurements_and_raw_attrs(void)
{
    struct fixture f;
    union power_supply_propval value;
    char text[4096];
    setup(&f, 3);
    assert(fg_observer_probe(&f.pdev) == 0);
    f.map.bytes[0x41a1] = f.map.bytes[0x41a7] = 0x80;
    assert(get(&f, POWER_SUPPLY_PROP_VOLTAGE_NOW, &value) == 0);
    assert(value.intval == 3999989);
    f.map.bytes[0x41a2] = f.map.bytes[0x41a8] = 1;
    assert(get(&f, POWER_SUPPLY_PROP_CURRENT_NOW, &value) == 0 && value.intval == -488);
    f.map.bytes[0x41a3] = f.map.bytes[0x41a9] = 0xff;
    f.map.bytes[0x41a2] = f.map.bytes[0x41a8] = 0xff;
    assert(get(&f, POWER_SUPPLY_PROP_CURRENT_NOW, &value) == 0 && value.intval == 488);
    f.map.bytes[0x41a7] = 0;
    assert(get(&f, POWER_SUPPLY_PROP_VOLTAGE_NOW, &value) == -EAGAIN);
    f.map.read_count = 0;
    for (size_t i = 0; fg_observer_attrs[i]; i++) {
        struct device_attribute *attr = (struct device_attribute *)fg_observer_attrs[i];
        assert(attr->show(&f.pdev.dev, attr, text) > 0);
    }
    done(&f);
}
static void legacy_rradc_attrs_unsupported(void)
{
    struct device_attribute *attrs[] = {
        &dev_attr_battery_temp_rr_raw,
        &dev_attr_rradc_realtime_status,
        &dev_attr_rradc_therm_config,
        &dev_attr_rradc_therm_period,
    };
    struct fixture f;
    char text[4096] = "unchanged";
    setup(&f, 2);
    assert(fg_observer_probe(&f.pdev) == 0);
    f.map.read_count = 0;
    for (size_t i = 0; i < ARRAY_SIZE(attrs); i++) {
        assert(attrs[i]->show(&f.pdev.dev, attrs[i], text) == -EOPNOTSUPP);
        assert(!strcmp(text, "unchanged"));
        assert(f.map.read_count == 0);
    }
    done(&f);
}
static void measurements_check_presence(void)
{
    const enum power_supply_property properties[] = {
        POWER_SUPPLY_PROP_VOLTAGE_NOW, POWER_SUPPLY_PROP_CURRENT_NOW,
    };
    for (size_t p = 0; p < ARRAY_SIZE(properties); p++) {
        for (unsigned int mode = 0; mode < 5; mode++) {
            struct fixture f;
            union power_supply_propval value = { .intval = 1234 };
            setup(&f, 3);
            assert(fg_observer_probe(&f.pdev) == 0);
            f.map.read_count = 0;
            if (mode == 0) f.map.bytes[0x4210] = 1;
            if (mode == 1 || mode == 2) {
                f.map.fail_at_count = mode == 1 ? 1 : 6;
                f.map.read_error = -ETIMEDOUT;
            }
            if (mode == 3) {
                f.map.change_at_count = 6;
                f.map.change_reg = 0x4210;
                f.map.change_value = 1;
            }
            assert(get(&f, properties[p], &value) ==
                   (mode == 1 || mode == 2 ? -ETIMEDOUT :
                    mode == 4 ? 0 : -ENODEV));
            assert(value.intval == (mode == 4 ? 0 : 1234));
            assert(f.map.read_count == (mode == 0 || mode == 1 ? 1U : 6U));
            done(&f);
        }
        struct fixture old;
        union power_supply_propval value;
        setup(&old, 2);
        assert(fg_observer_probe(&old.pdev) == 0);
        old.map.read_count = 0;
        assert(get(&old, properties[p], &value) == 0);
        assert(old.map.read_count == 4);
        done(&old);
    }
}
static void raw_attrs_propagate_read_errors(void)
{
    const struct {
        struct device_attribute *attr;
        unsigned int reg;
        bool rradc;
    } attrs[] = {
        { &dev_attr_battery_temp_status, 0x4106, false },
        { &dev_attr_battery_presence_status, 0x4107, false },
        { &dev_attr_battery_temp_rr_raw, 0x4288, true },
        { &dev_attr_rradc_realtime_status, 0x4210, true },
        { &dev_attr_rradc_therm_config, 0x4281, true },
        { &dev_attr_rradc_therm_period, 0x4282, true },
        { &dev_attr_algorithm_peek_config, 0x41ee, false },
        { &dev_attr_memory_realtime_status, 0x4310, false },
        { &dev_attr_memory_arbitration_config, 0x4340, false },
        { &dev_attr_memory_interface_config, 0x4350, false },
        { &dev_attr_dma_status, 0x4370, false },
        { &dev_attr_dma_config, 0x4371, false },
    };
    const int errors[] = { -EIO, -ETIMEDOUT };
    char text[4096], unchanged[4096];
    memset(unchanged, 0xa5, sizeof(unchanged));
    for (int count = 2; count <= 3; count++) {
        struct fixture f;
        setup(&f, count);
        assert(fg_observer_probe(&f.pdev) == 0);
        for (size_t i = 0; i < ARRAY_SIZE(attrs); i++) {
            if (count == 2 && attrs[i].rradc) continue;
            for (size_t j = 0; j < ARRAY_SIZE(errors); j++) {
                f.map.fail_reg = attrs[i].reg;
                f.map.read_error = errors[j];
                f.map.read_count = 0;
                memcpy(text, unchanged, sizeof(text));
                assert(attrs[i].attr->show(&f.pdev.dev, attrs[i].attr, text) == errors[j]);
                assert(!memcmp(text, unchanged, sizeof(text)));
                assert(f.map.read_count == 1 && f.map.reads[0] == attrs[i].reg);
            }
        }
        done(&f);
    }
}
int main(void)
{
    presence();
    legacy_and_independent_nodes();
    identities_and_faults();
    old_measurements_and_raw_attrs();
    legacy_rradc_attrs_unsupported();
    measurements_check_presence();
    raw_attrs_propagate_read_errors();
    printf("observer actual-source: %u fixtures + all 256 presence bytes passed; zero writes\n", cases);
    return 0;
}
