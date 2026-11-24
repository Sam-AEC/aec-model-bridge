using System;
using System.IO;
using System.Text;
using System.Threading;
using System.Threading.Tasks;
using RevitBridge.Bridge;
using Xunit;

namespace RevitBridge.Tests;

// Frame codec of the named-pipe transport (ADR 0021). The Python client tests the same layout in
// packages/mcp-server-revit/tests/test_pipe_transport.py.
public class PipeFramingTests
{
    [Fact]
    public void Encode_writes_little_endian_length_then_utf8_json()
    {
        var frame = PipeFraming.Encode("{\"a\":\"é\"}", 100);
        var body = Encoding.UTF8.GetBytes("{\"a\":\"é\"}");
        Assert.Equal(new byte[] { (byte)body.Length, 0, 0, 0 }, new[] { frame[0], frame[1], frame[2], frame[3] });
        var rest = new byte[frame.Length - 4];
        Array.Copy(frame, 4, rest, 0, rest.Length);
        Assert.Equal(body, rest);
    }

    [Fact]
    public void Encode_refuses_a_frame_over_the_limit()
    {
        Assert.Throws<InvalidDataException>(() => PipeFraming.Encode(new string('a', 20), 10));
    }

    [Fact]
    public async Task Read_returns_the_body_of_a_whole_frame()
    {
        var stream = new MemoryStream(PipeFraming.Encode("{\"path\":\"/health\"}", 100));
        var body = await PipeFraming.ReadFrame(stream, 100, 5000, CancellationToken.None);
        Assert.Equal("{\"path\":\"/health\"}", Encoding.UTF8.GetString(body!));
    }

    [Fact]
    public async Task Read_refuses_an_oversize_declared_length_without_a_body()
    {
        var stream = new MemoryStream(new byte[] { 0x01, 0x00, 0x00, 0x01 }); // 16 MiB + 1, no body follows
        await Assert.ThrowsAsync<InvalidDataException>(() => PipeFraming.ReadFrame(stream, PipeFraming.MaxRequestFrameBytes, 5000, CancellationToken.None));
    }

    [Theory]
    [InlineData(new byte[0])]
    [InlineData(new byte[] { 0x05, 0x00 })]
    [InlineData(new byte[] { 0x05, 0x00, 0x00, 0x00, 0x7b })]
    public async Task Read_returns_null_for_a_truncated_frame(byte[] data)
    {
        Assert.Null(await PipeFraming.ReadFrame(new MemoryStream(data), 100, 5000, CancellationToken.None));
    }

    [Fact]
    public async Task Write_then_read_round_trips()
    {
        var stream = new MemoryStream();
        await PipeFraming.WriteFrame(stream, "{\"status\":200,\"body\":{}}", CancellationToken.None);
        stream.Position = 0;
        var body = await PipeFraming.ReadFrame(stream, PipeFraming.MaxResponseFrameBytes, 5000, CancellationToken.None);
        Assert.Equal("{\"status\":200,\"body\":{}}", Encoding.UTF8.GetString(body!));
    }

    [Theory]
    [InlineData("Bearer abc", true)]
    [InlineData("Bearer abd", false)]
    [InlineData("Bearer ab", false)]
    [InlineData("Bearer abcd", false)]
    [InlineData("", false)]
    [InlineData(null, false)]
    public void Token_must_match_exactly(string? presented, bool expected)
    {
        Assert.Equal(expected, PipeFraming.TokenMatches(presented, "Bearer abc"));
    }
}
