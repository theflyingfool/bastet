from bastet.core.units import format_size, parse_size, ram_label, same_value


def test_parse_size():
    assert parse_size("16 GB") == 16 * 10**9
    assert parse_size("15.5GiB") == int(15.5 * 2**30)
    assert parse_size("4TB") == 4 * 10**12
    assert parse_size(1024) == 1024
    assert parse_size("lots") is None
    assert parse_size(True) is None


def test_format_size():
    assert format_size(512110190592) == "512 GB"
    assert format_size(1_500_000_000_000) == "1.5 TB"
    assert format_size(4_000_000_000_000) == "4 TB"
    assert format_size(85899345920, binary=True) == "80 GB"


def test_ram_label_rounds_up_to_installed_size():
    assert ram_label(16165428) == "16 GB"
    assert ram_label(4005284) == "4 GB"
    assert ram_label(131_900_000) == "128 GB"
    assert ram_label(2097152) == "2 GB"


def test_same_value():
    assert same_value("ram", "128 GB", "126 GB")
    assert not same_value("ram", "128 GB", "96 GB")
    assert same_value("os", "Debian 13 ", "debian 13")
    assert not same_value("os", "Debian 12", "Debian 13")
    assert same_value("cpu_cores", 4, 4)
